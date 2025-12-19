from mcp.server.fastmcp import FastMCP, Context, Image
import socket
import json
import asyncio
import logging
import tempfile
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List
import os
from pathlib import Path
import base64
from urllib.parse import urlparse
from ..connect import get_blender_connection, mcp, logger  # <-- mcpとloggerを追加
from ..experiment_logger import get_experiment_logger  # 実験ロガーを追加

@mcp.tool()
def execute_blender_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Blender. Make sure to do it step-by-step by breaking it into smaller chunks.
    
    Parameters:
    - code: The Python code to execute
    """
    # ツール実行開始時にロガーを取得
    exp_logger = get_experiment_logger()
    
    try:
        # Get the global connection
        blender = get_blender_connection()
        result = blender.send_command("execute_code", {"code": code})
        
        # 成功ログを記録
        if exp_logger:
            exp_logger.log_tool_call("execute_blender_code", {"code": code}, result)
            
        return f"Code executed successfully: {result.get('result', '')}"
    except Exception as e:
        logger.error(f"Error executing code: {str(e)}")
        
        # エラーログを記録
        if exp_logger:
            exp_logger.log_error("EXECUTION_ERROR", str(e), {"tool": "execute_blender_code", "code": code})
            
        return f"Error executing code: {str(e)}"


@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Get detailed information about the current Blender scene"""
    exp_logger = get_experiment_logger()
    
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_scene_info")
        
        # ログ記録
        if exp_logger:
            exp_logger.log_tool_call("get_scene_info", {}, result)
        
        # Just return the JSON representation of what Blender sent us
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene info from Blender: {str(e)}")
        
        if exp_logger:
            exp_logger.log_error("SCENE_INFO_ERROR", str(e), {"tool": "get_scene_info"})
        
        return f"Error getting scene info: {str(e)}"


@mcp.tool()
def get_object_info(ctx: Context, object_name: str) -> str:
    """
    Get detailed information about a specific object in the Blender scene.
    
    Parameters:
    - object_name: The name of the object to get information about
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_object_info", {"name": object_name})
        
        # Just return the JSON representation of what Blender sent us
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting object info from Blender: {str(e)}")
        return f"Error getting object info: {str(e)}"


@mcp.tool()
def get_viewport_screenshot(ctx: Context, max_size: int = 800) -> Image:
    """
    Capture a screenshot of the current Blender 3D viewport.
    
    Parameters:
    - max_size: Maximum size in pixels for the largest dimension (default: 800)
    
    Returns the screenshot as an Image.
    """
    try:
        blender = get_blender_connection()
        
        # Create temp file path
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"blender_screenshot_{os.getpid()}.png")
        
        result = blender.send_command("get_viewport_screenshot", {
            "max_size": max_size,
            "filepath": temp_path,
            "format": "png"
        })
        
        if "error" in result:
            raise Exception(result["error"])
        
        if not os.path.exists(temp_path):
            raise Exception("Screenshot file was not created")
        
        # Read the file
        with open(temp_path, 'rb') as f:
            image_bytes = f.read()
        
        # Delete the temp file
        os.remove(temp_path)
        
        return Image(data=image_bytes, format="png")
        
    except Exception as e:
        logger.error(f"Error capturing screenshot: {str(e)}")
        raise Exception(f"Screenshot failed: {str(e)}")


@mcp.tool()
def set_object_dimensions(ctx: Context, object_name: str, width_x: float = None, depth_y: float = None, height_z: float = None) -> str:
    """
    指定したオブジェクトの絶対寸法（実寸メートル）を設定します。
    重要: サイズ変更の際は、倍率計算のミスを防ぐため、scale操作ではなく必ずこのツールを使用してください。
    
    Args:
        object_name: 対象のオブジェクト名
        width_x: X軸方向の幅 (m) - 変更しない場合はNone
        depth_y: Y軸方向の奥行き (m) - 変更しない場合はNone
        height_z: Z軸方向の高さ (m) - 変更しない場合はNone
    """
    exp_logger = get_experiment_logger()
    blender = get_blender_connection()
    
    # 変更するパラメータのみを含む辞書を作成
    dims = {}
    if width_x is not None: dims['x'] = width_x
    if depth_y is not None: dims['y'] = depth_y
    if height_z is not None: dims['z'] = height_z
    
    if not dims:
        warning_msg = "警告: 変更する寸法が指定されていません。"
        if exp_logger:
            exp_logger.log_error("DIMENSION_ERROR", "No dimensions specified", {"tool": "set_object_dimensions", "object": object_name})
        return warning_msg

    # Blender内で実行するPythonコード
    # 修正: view_layer.update()を追加し、変更の確定と検証を行うように強化
    code = f"""
import bpy
import math

try:
    obj = bpy.data.objects.get('{object_name}')
    if not obj:
        print(f"Error: Object '{object_name}' not found")
    else:
        # 1. 現在の寸法を取得
        current_dims = list(obj.dimensions)
        
        # 2. 目標寸法を設定
        target_dims = current_dims[:]
        {'target_dims[0] = ' + str(width_x) if width_x is not None else ''}
        {'target_dims[1] = ' + str(depth_y) if depth_y is not None else ''}
        {'target_dims[2] = ' + str(height_z) if height_z is not None else ''}
        
        # 3. 寸法を適用
        obj.dimensions = target_dims
        
        # 4. ビューレイヤーを更新して変更を確定・伝播させる (重要: これがないと反映されない、または戻ることがある)
        bpy.context.view_layer.update()
        
        # 5. 結果を再確認 (ドライバや制約によるリセットを検知)
        final_dims = list(obj.dimensions)
        
        # 許容誤差 (1mm)
        tolerance = 0.001
        is_x_ok = abs(final_dims[0] - target_dims[0]) < tolerance or {str(width_x is None)}
        is_y_ok = abs(final_dims[1] - target_dims[1]) < tolerance or {str(depth_y is None)}
        is_z_ok = abs(final_dims[2] - target_dims[2]) < tolerance or {str(height_z is None)}
        
        if is_x_ok and is_y_ok and is_z_ok:
            print(f"Success: Updated dimensions for {{obj.name}} to {{final_dims}}")
        else:
            print(f"Warning: Dimensions were reset or constrained after update. Target: {{target_dims}}, Actual: {{final_dims}}.\\nCheck for Drivers, Keyframes, or Parent constraints controlling the scale.")
            
except Exception as e:
    print(f"Error setting dimensions: {{e}}")
"""
    
    try:
        result = blender.send_command("execute_code", {"code": code})
        
        if "error" in result:
            if exp_logger:
                exp_logger.log_error("DIMENSION_SET_ERROR", result['error'], {
                    "tool": "set_object_dimensions", 
                    "object": object_name,
                    "dimensions": dims
                })
            return f"エラー: {result['error']}"
        
        # 実行結果文字列を取得
        output_msg = result.get('result', '')
        
        # 警告が含まれているかチェック
        if "Warning" in output_msg:
             return f"寸法変更に失敗した可能性があります: {output_msg}"

        # 成功ログ
        if exp_logger:
            exp_logger.log_tool_call("set_object_dimensions", {
                "object_name": object_name,
                "width_x": width_x,
                "depth_y": depth_y,
                "height_z": height_z
            }, result)
        
        return f"寸法を更新しました: {output_msg}"
    
    except Exception as e:
        if exp_logger:
            exp_logger.log_error("DIMENSION_SET_EXCEPTION", str(e), {
                "tool": "set_object_dimensions",
                "object": object_name,
                "dimensions": dims
            })
        return f"エラー: {str(e)}"


@mcp.tool()
def create_or_update_object(ctx: Context, name: str, object_type: str = "CUBE", 
                          width_x: float = 1.0, depth_y: float = 1.0, height_z: float = 1.0,
                          loc_x: float = 0.0, loc_y: float = 0.0, loc_z: float = 0.0) -> str:
    """
    オブジェクトを作成、または既存の同名オブジェクトを更新します。
    重複作成（Example.001など）を防ぐために、必ずこのツールを使用してください。
    
    Args:
        name: オブジェクトの一意な名前 (例: 'Wall_South', 'Main_Door')
        object_type: 'CUBE', 'PLANE', 'SPHERE', 'CYLINDER'
        width_x, depth_y, height_z: 寸法 (m)
        loc_x, loc_y, loc_z: 配置座標 (m)
    """
    exp_logger = get_experiment_logger()
    blender = get_blender_connection()

    # Blender側で実行するスクリプト
    # 存在確認 -> 作成/取得 -> 寸法適用 -> 座標適用 -> 原点正規化 を一気に行う
    code = f"""
import bpy
import math

name = '{name}'
obj_type = '{object_type.upper()}'
dims = ({width_x}, {depth_y}, {height_z})
loc = ({loc_x}, {loc_y}, {loc_z})

# 1. 既存チェック & 取得/作成
target_obj = bpy.data.objects.get(name)

if target_obj is None:
    # 新規作成
    if obj_type == 'CUBE':
        bpy.ops.mesh.primitive_cube_add(size=1)
    elif obj_type == 'PLANE':
        bpy.ops.mesh.primitive_plane_add(size=1)
    elif obj_type == 'SPHERE':
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5)
    elif obj_type == 'CYLINDER':
        bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1) # Default
    
    target_obj = bpy.context.active_object
    target_obj.name = name
    action = "Created"
else:
    # 既存選択
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj
    action = "Updated"

# 2. 寸法の適用 (Dimensionsプロパティを使用)
target_obj.dimensions = dims

# 3. スケールの適用 (重要: これをやらないと後の計算が狂う)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

# 4. 原点の正規化 (重要: 重心を原点にする)
# これにより LLM が指定した座標 = オブジェクトの中心 となり、ズレがなくなる
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')

# 5. 座標の移動
target_obj.location = loc

print(f"{{action}} object '{{name}}' at {{loc}} with size {{dims}}")
"""
    
    try:
        result = blender.send_command("execute_code", {"code": code})
        
        # ログ記録
        if exp_logger:
            exp_logger.log_tool_call("create_or_update_object", {
                "name": name, "action": "create/update", "params": {"size": [width_x, depth_y, height_z]}
            }, result)
            
        return f"Successfully processed '{name}': {result.get('result', 'No output')}"
        
    except Exception as e:
        if exp_logger:
            exp_logger.log_error("CREATE_UPDATE_ERROR", str(e), {"tool": "create_or_update_object"})
        return f"Error: {str(e)}"


@mcp.tool()
def normalize_object_transform(ctx: Context, object_name: str) -> str:
    """
    オブジェクトの「座標ズレ」や「回転軸のおかしさ」を修正するメンテナンスツール。
    操作点がずれていると感じたらこれを呼び出してください。
    
    行う処理:
    1. Apply Scale (スケールを(1,1,1)に確定)
    2. Origin to Geometry (原点をオブジェクトのど真ん中に移動)
    3. Floor Snap (オプション: 最下部をZ=0に合わせる処理は今回は除外、純粋な正規化のみ)
    """
    exp_logger = get_experiment_logger()
    blender = get_blender_connection()
    
    code = f"""
import bpy
obj = bpy.data.objects.get('{object_name}')
if obj:
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    # スケール適用
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    # 原点移動
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    
    print(f"Normalized transform for {{obj.name}}")
else:
    print(f"Object {{object_name}} not found")
"""
    try:
        result = blender.send_command("execute_code", {"code": code})
        
        # ログ記録
        if exp_logger:
            exp_logger.log_tool_call("normalize_object_transform", {
                "object_name": object_name
            }, result)
            
        return f"Normalized '{object_name}': {result.get('result', '')}"
    except Exception as e:
        if exp_logger:
            exp_logger.log_error("NORMALIZE_ERROR", str(e), {"tool": "normalize_object_transform", "object": object_name})
        return f"Error: {str(e)}"

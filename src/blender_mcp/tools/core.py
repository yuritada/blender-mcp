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

@mcp.tool()
def execute_blender_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Blender. Make sure to do it step-by-step by breaking it into smaller chunks.
    
    Parameters:
    - code: The Python code to execute
    """
    try:
        # Get the global connection
        blender = get_blender_connection()
        result = blender.send_command("execute_code", {"code": code})
        return f"Code executed successfully: {result.get('result', '')}"
    except Exception as e:
        logger.error(f"Error executing code: {str(e)}")
        return f"Error executing code: {str(e)}"


@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Get detailed information about the current Blender scene"""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_scene_info")
        
        # Just return the JSON representation of what Blender sent us
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene info from Blender: {str(e)}")
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
    blender = get_blender_connection()
    
    # 変更するパラメータのみを含む辞書を作成
    dims = {}
    if width_x is not None: dims['x'] = width_x
    if depth_y is not None: dims['y'] = depth_y
    if height_z is not None: dims['z'] = height_z
    
    if not dims:
        return "警告: 変更する寸法が指定されていません。"

    # Blender内で実行するPythonコード
    # dimensionsプロパティに直接値を代入することで、Scaleを自動的に逆算させます
    code = f"""
import bpy
try:
    obj = bpy.data.objects.get('{object_name}')
    if not obj:
        print(f"Error: Object '{object_name}' not found")
    else:
        # 現在の寸法を取得
        current_dims = list(obj.dimensions)
        
        # 指定された軸のみ更新
        new_dims = current_dims[:]
        {'new_dims[0] = ' + str(width_x) if width_x is not None else ''}
        {'new_dims[1] = ' + str(depth_y) if depth_y is not None else ''}
        {'new_dims[2] = ' + str(height_z) if height_z is not None else ''}
        
        # dimensionsに代入（これで実寸が確定する）
        obj.dimensions = new_dims
        
        # 変更を適用（Scaleを1.0にリセットしたい場合。実験によっては不要だが、安全のため推奨）
        # bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        
        print(f"Updated dimensions for {{obj.name}}: {{list(obj.dimensions)}}")
except Exception as e:
    print(f"Error setting dimensions: {{e}}")
"""
    
    # execute_code ではなく、このロジックを直接送るか、あるいは execute_code 経由で実行
    # ここでは既存の仕組みに合わせて send_command か execute_code を使用
    result = blender.send_command("execute_code", {"code": code})
    
    if "error" in result:
        return f"エラー: {result['error']}"
    
    return f"寸法を更新しました: {result.get('result', '')}"

from mcp.server.fastmcp import Context
import json
from ..connect import get_blender_connection, mcp, logger

@mcp.tool()
def apply_grid_layout(ctx: Context, object_type: str, rows: int, cols: int, spacing: float = 2.0) -> str:
    """
    Apply a deterministic grid layout rule to the scene.
    
    Parameters:
    - object_type: Type of object to place ('cube', 'sphere', 'monkey')
    - rows: Number of rows in the grid
    - cols: Number of columns in the grid
    - spacing: Distance between objects (default: 2.0)
    """
    try:
        # 接続の取得
        blender = get_blender_connection()
        
        # addon.py で定義した 'create_grid_layout' を呼び出す
        # ここではPythonコードを送るのではなく、パラメータを送る
        result = blender.send_command("create_grid_layout", {
            "object_type": object_type,
            "rows": rows,
            "cols": cols,
            "spacing": spacing
        })
        
        if "error" in result:
            return f"Rule Error: {result['error']}"
            
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error applying grid rule: {str(e)}")
        return f"System Error: {str(e)}"
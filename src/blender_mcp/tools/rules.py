from mcp.server.fastmcp import Context
import json
from ..connect import get_blender_connection, mcp, logger

@mcp.tool()
def apply_grid_layout(ctx: Context, object_type: str, rows: int, cols: int, spacing: float = 2.0) -> str:
    """
    指定されたオブジェクトをグリッド状に配置するプロシージャル・ルールを適用します。

    Parameters:
    - object_type: Object type ('cube', 'sphere', 'monkey', etc.)
    - rows: Number of rows
    - cols: Number of columns
    - spacing: Distance between objects
    """
    try:
        # Blender接続
        blender = get_blender_connection()

        # addon.py 側の create_grid_layout を呼び出す
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

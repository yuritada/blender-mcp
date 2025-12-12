# src/blender_mcp/main.py

# 不要な import は削除し、以下のようにシンプルにします
from blender_mcp.connect import mcp

# 重要: 各モジュールを import することで、@mcp.tool デコレータが実行され、
# mcp オブジェクトにツールが登録されます。
import blender_mcp.tools.core
import blender_mcp.tools.assets.polyhaven
import blender_mcp.tools.assets.hyper3d
import blender_mcp.tools.assets.sketchfab
import blender_mcp.tools.assets.prompt
import blender_mcp.tools.rules
import blender_mcp.tools.knowledge
import blender_mcp.tools.standards

def main():
    """Run the MCP server"""
    # 既に tools 内で登録が完了している mcp インスタンスを起動
    mcp.run()

if __name__ == "__main__":
    main()
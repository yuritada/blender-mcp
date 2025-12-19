"""
Blender AI Client - カスタムPythonクライアント
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# UI向上のためのライブラリ
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status
from rich.prompt import Prompt

# 環境変数の読み込み
load_dotenv()

# 設定
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5-coder:32b")
BLENDER_HOST = os.getenv("BLENDER_HOST", "localhost")
BLENDER_PORT = os.getenv("BLENDER_PORT", "9876")
MCP_CMD = os.getenv("MCP_COMMAND", "uv")
MCP_ARGS = os.getenv("MCP_ARGS", "run,blender-mcp").split(",")

os.environ["BLENDER_HOST"] = BLENDER_HOST
os.environ["BLENDER_PORT"] = BLENDER_PORT

console = Console()

# システムプロンプト（更新版）
SYSTEM_PROMPT = """
あなたはBlenderのPythonスクリプト(bpy)のエキスパートです。
ユーザーの指示に従い、提供されたツールを使用して3Dシーンを操作してください。

ルール:
0. 【最優先: 記憶の参照】何かを作成・変更する指示を受けたら、作業を始める前に必ず `get_architectural_rules()` を呼び出し、過去に学習した「ユーザーの好み」や「成功パターン」を確認してください。該当するルールがあれば、それを思考に含めてください。
1. コードを生成する場合は、必ず実行可能なPythonコードを `execute_blender_code` ツール経由で送信するか、ユーザーに提示してください。
2. 簡潔かつ正確に答えてください。
3. ユーザーが曖昧な指示をした場合は、Blenderの一般的な操作（例: 原点に作成など）を常識的に補完して実行してください。
4. 【重要: 法的検証】建築要素（階段、部屋、窓など）を作成・変更する際は、必ず `get_building_standards` で法的要件を確認し、作成直後に `validate_object_compliance` で適合性を検証してください。違反がある場合は自律的に修正してください。
5. 【重要: サイズ指定の厳格化】オブジェクトの大きさ設定には、計算ミスを防ぐため `obj.scale` の操作を**禁止**します。代わりに必ず `set_object_dimensions` ツールを使用し、目標とする実寸(メートル)を直接指定してください。
6. 【学習と適応】ユーザーからの指示だけでなく、**あなた自身がエラー修正を行う中で発見した「成功パターン」や「避けるべき設定」も、将来の教訓として積極的に `add_architectural_rule` で保存してください。**
   - 例: 「ドアの高さを修正して合格した」→ 保存:「[Door] ドア高さは2.0m以上で設定すると一発で合格する」
   - タイミング: `validate_object_compliance` で合格が出た直後、タスク完了報告の前に必ず行ってください。
"""

async def run_chat_loop():
    """メインのチャットループを実行"""
    server_params = StdioServerParameters(
        command=MCP_CMD,
        args=MCP_ARGS,
        env=os.environ.copy()
    )

    console.print(Panel(
        f"[bold green]Starting Blender AI Client[/bold green]\n"
        f"Model: [cyan]{MODEL_NAME}[/cyan]\n"
        f"Target: Blender at {BLENDER_HOST}:{BLENDER_PORT}",
        title="Welcome"
    ))

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools_result = await session.list_tools()
                ollama_tools = []

                for tool in tools_result.tools:
                    ollama_tools.append({
                        'type': 'function',
                        'function': {
                            'name': tool.name,
                            'description': tool.description,
                            'parameters': tool.inputSchema
                        }
                    })

                console.print(f"[dim]Loaded {len(ollama_tools)} tools from Blender MCP.[/dim]")

                messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

                while True:
                    console.print("\n[bold cyan]You:[/bold cyan] ", end="")
                    try:
                        user_input = Prompt.ask("")
                    except (KeyboardInterrupt, EOFError):
                        console.print("\n[dim]Exiting...[/dim]")
                        break

                    if user_input.lower() in ['quit', 'exit', 'q']:
                        console.print("[dim]Goodbye![/dim]")
                        break

                    if not user_input.strip():
                        continue

                    messages.append({'role': 'user', 'content': user_input})

                    # AIの応答待ちループ
                    with console.status(
                        f"[bold yellow]Thinking with {MODEL_NAME}...[/bold yellow]",
                        spinner="dots"
                    ) as status:
                        
                        # 初回のリクエスト
                        response = ollama.chat(
                            model=MODEL_NAME,
                            messages=messages,
                            tools=ollama_tools,
                        )
                        messages.append(response.message)

                        # ★修正箇所: whileループに変更して、ツールが続く限り実行し続ける
                        while response.message.tool_calls:
                            status.update("[bold blue]Executing Blender Tools...[/bold blue]")
                            
                            for tool_call in response.message.tool_calls:
                                fn_name = tool_call.function.name
                                fn_args = tool_call.function.arguments

                                console.print(f" -> [dim]Calling tool: {fn_name}[/dim]")

                                try:
                                    result = await session.call_tool(fn_name, arguments=fn_args)
                                    tool_output = result.content[0].text

                                    messages.append({
                                        'role': 'tool',
                                        'content': tool_output,
                                    })
                                    
                                    # 長い出力は省略して表示
                                    display_output = tool_output[:100].replace('\n', ' ')
                                    console.print(f"    [dim green]Result: {display_output}...[/dim green]")

                                except Exception as e:
                                    error_msg = f"Error executing tool {fn_name}: {str(e)}"
                                    console.print(f"[bold red]{error_msg}[/bold red]")
                                    messages.append({
                                        'role': 'tool',
                                        'content': error_msg,
                                    })

                            # ツールの結果を持って、再度AIに問い合わせ（次の行動を決定）
                            status.update("[bold green]Reasoning next step...[/bold green]")
                            response = ollama.chat(
                                model=MODEL_NAME,
                                messages=messages,
                                tools=ollama_tools, # ツール定義を再送して、連続呼び出しを可能にする
                            )
                            messages.append(response.message)

                        # ループを抜けたら、それが最終回答（テキスト）
                        ai_content = response.message.content

                    console.print("\n[bold magenta]AI:[/bold magenta]")
                    if ai_content:
                        console.print(Markdown(ai_content))
                    else:
                        console.print("[dim](No response content)[/dim]")

    except ConnectionRefusedError:
        console.print("[bold red]Connection Error:[/bold red] Could not connect to Blender.")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()

def main():
    asyncio.run(run_chat_loop())

if __name__ == "__main__":
    main()
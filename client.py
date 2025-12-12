"""
Blender AI Client - カスタムPythonクライアント

Ollama + MCP を使ってBlenderを操作するAIクライアント。
richライブラリによるリッチな表示、エラーハンドリング、
システムプロンプトによる精度向上を実装。
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
# カンマ区切り文字列をリストに変換
MCP_ARGS = os.getenv("MCP_ARGS", "run,blender-mcp").split(",")

# Blender接続用の環境変数をセット（MCPサーバープロセスに渡すため）
os.environ["BLENDER_HOST"] = BLENDER_HOST
os.environ["BLENDER_PORT"] = BLENDER_PORT

console = Console()

# システムプロンプト：AIの役割を定義
# ここで役割を明確にすることで、bpyモジュールを使った正確なコード生成を促します
SYSTEM_PROMPT = """
あなたはBlenderのPythonスクリプト(bpy)のエキスパートです。
ユーザーの指示に従い、提供されたツールを使用して3Dシーンを操作してください。

ルール:
1. コードを生成する場合は、必ず実行可能なPythonコードを `execute_blender_code` ツール経由で送信するか、ユーザーに提示してください。
2. 簡潔かつ正確に答えてください。
3. ユーザーが曖昧な指示をした場合は、Blenderの一般的な操作（例: 原点に作成、サイズは1mなど）を常識的に補完して実行してください。
"""


async def run_chat_loop():
    """メインのチャットループを実行"""
    # MCPサーバー起動パラメータ
    server_params = StdioServerParameters(
        command=MCP_CMD,
        args=MCP_ARGS,
        env=os.environ.copy()  # 現在の環境変数（BLENDER_HOST等含む）を引き継ぐ
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

                # ツール一覧取得
                tools_result = await session.list_tools()
                ollama_tools = []

                # Ollama用にツール定義を変換
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

                # 会話履歴の初期化
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

                    # AIの応答待ち（スピナー表示）
                    with console.status(
                        f"[bold yellow]Thinking with {MODEL_NAME}...[/bold yellow]",
                        spinner="dots"
                    ) as status:

                        # 1. Ollamaへの問い合わせ
                        response = ollama.chat(
                            model=MODEL_NAME,
                            messages=messages,
                            tools=ollama_tools,
                        )

                        messages.append(response.message)

                        # 2. ツール実行が必要な場合
                        if response.message.tool_calls:
                            status.update("[bold blue]Executing Blender Tools...[/bold blue]")

                            for tool_call in response.message.tool_calls:
                                fn_name = tool_call.function.name
                                fn_args = tool_call.function.arguments

                                console.print(f" -> [dim]Calling tool: {fn_name}[/dim]")

                                try:
                                    # ツール実行
                                    result = await session.call_tool(fn_name, arguments=fn_args)
                                    tool_output = result.content[0].text

                                    # 結果を履歴に追加
                                    messages.append({
                                        'role': 'tool',
                                        'content': tool_output,
                                    })

                                    # 結果の一部を表示（改行を空白に置換して見やすく）
                                    display_output = tool_output[:100].replace('\n', ' ')
                                    console.print(f"    [dim green]Result: {display_output}...[/dim green]")

                                except Exception as e:
                                    error_msg = f"Error executing tool {fn_name}: {str(e)}"
                                    console.print(f"[bold red]{error_msg}[/bold red]")
                                    # エラーもAIに返して、修正を促す
                                    messages.append({
                                        'role': 'tool',
                                        'content': error_msg,
                                    })

                            # 3. ツール結果を踏まえて最終回答を生成
                            status.update("[bold green]Generating final response...[/bold green]")
                            final_response = ollama.chat(
                                model=MODEL_NAME,
                                messages=messages,
                            )
                            ai_content = final_response.message.content
                            messages.append(final_response.message)

                        else:
                            # ツール使用なし
                            ai_content = response.message.content

                    # AIの回答を表示（Markdownレンダリング）
                    console.print("\n[bold magenta]AI:[/bold magenta]")
                    if ai_content:
                        console.print(Markdown(ai_content))
                    else:
                        console.print("[dim](No response content)[/dim]")

    except ConnectionRefusedError:
        console.print("[bold red]Connection Error:[/bold red] Could not connect to Blender.")
        console.print("[dim]Make sure Blender is running and the BlenderMCP addon is active.[/dim]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        console.print("[dim]Make sure Blender is running and the Addon is active.[/dim]")
        import traceback
        traceback.print_exc()


def main():
    """エントリーポイント"""
    # Windows等の非同期ループ対応
    # if os.name == 'nt':
    #     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_chat_loop())


if __name__ == "__main__":
    main()

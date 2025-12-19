"""
Blender AI Client - カスタムPythonクライアント
トークン集計とログ機能を統合したバージョン
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
from rich.table import Table  # 集計表示用にTableを追加

# --- [追加] srcモジュールへのパスを通す ---
# これにより、src/blender_mcp 配下のモジュールをインポート可能にします
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))
from blender_mcp.experiment_logger import ExperimentLogger

# 環境変数の読み込み
load_dotenv()

# 設定
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5-coder:32b") # ユーザー指定のモデルに変更
BLENDER_HOST = os.getenv("BLENDER_HOST", "localhost")
BLENDER_PORT = os.getenv("BLENDER_PORT", "9876")
MCP_CMD = os.getenv("MCP_COMMAND", "uv")
MCP_ARGS = os.getenv("MCP_ARGS", "run,blender-mcp").split(",")

os.environ["BLENDER_HOST"] = BLENDER_HOST
os.environ["BLENDER_PORT"] = BLENDER_PORT

console = Console()

# --- [修正] ロガーの初期化：プレフィックスとサブディレクトリを指定 ---
LOG_DIR = os.getenv("BLENDER_MCP_LOG_DIR", "logs")

# クライアント専用のサブディレクトリを作成し、サーバー側のログと明確に分離
logger = ExperimentLogger(LOG_DIR, file_prefix="chat_log_", sub_dir="client")

# --- [追加] ツール名と日本語説明の対応表 ---
TOOL_DESCRIPTIONS = {
    # Core Tools
    "execute_blender_code": "🛠️ BlenderでPythonスクリプトを実行しています...",
    "get_scene_info": "📊 Blenderシーンの情報を取得しています...",
    "get_object_info": "🔍 オブジェクトの詳細情報を確認しています...",
    "get_viewport_screenshot": "📸 現在のビューポートをキャプチャしています...",
    "set_object_dimensions": "📏 オブジェクトの寸法を正確に設定しています...",
    "create_or_update_object": "🏗️ オブジェクトを作成または更新しています...",
    "normalize_object_transform": "🔧 オブジェクトの座標・変形を正規化しています...",
    
    # Rules & Memory
    "get_architectural_rules": "🧠 過去の学習データ・建築ルールを検索しています...",
    "add_architectural_rule": "📝 新しいルールを記憶に保存しています...",
    
    # Standards & Validation
    "get_building_standards": "⚖️ 建築基準法および法的要件を確認しています...",
    "validate_object_compliance": "✅ 作成されたオブジェクトの法令適合性を検証しています...",
    "validate_scene_rules": "🏠 シーン全体の建築基準を一括検証しています...",
    
    # Knowledge Base
    "search_knowledge_base": "📚 ナレッジベースから技術情報を検索しています...",
    
    # Assets
    "search_polyhaven": "🎨 Poly Havenでテクスチャ・HDRiを検索しています...",
    "search_sketchfab": "🗿 Sketchfabで3Dモデルを検索しています...",
    "search_hyper3d": "🧊 Hyper3Dでアセットを検索しています...",
}

def get_tool_display_message(name, args):
    """ツール名と引数から表示用メッセージを作成"""
    base_msg = TOOL_DESCRIPTIONS.get(name, f"🔧 ツール [{name}] を実行しています...")
    
    # 引数情報を少し付加するとより分かりやすくなります（オプション）
    if name == "execute_blender_code":
        # コードの内容は長すぎるので省略
        return base_msg
    elif name == "validate_object_compliance":
        obj_name = args.get("object_name", "Unknown")
        rule_id = args.get("rule_id", "Unknown")
        return f"{base_msg} (対象: {obj_name}, ルール: {rule_id})"
    elif name in ["get_object_info", "set_object_dimensions", "normalize_object_transform"]:
        obj_name = args.get("object_name", "Unknown")
        return f"{base_msg} (対象: {obj_name})"
    elif name == "create_or_update_object":
        obj_name = args.get("name", "Unknown")
        obj_type = args.get("object_type", "CUBE")
        return f"{base_msg} (名前: {obj_name}, 種類: {obj_type})"
    elif "query" in args:
        return f"{base_msg} (検索語: {args['query']})"
    elif "category" in args and args["category"]:
        return f"{base_msg} (カテゴリ: {args['category']})"
    
    return base_msg

SYSTEM_PROMPT = """
あなたはBlenderのPythonスクリプト(bpy)のエキスパートです。

## 重要な制約事項

1. **オブジェクト作成**: 
   - 新しいオブジェクトを作成する際は、必ず `create_or_update_object` ツールを使用してください
   - 重複防止のため、適切な一意の名前を付けてください（例: 'Main_Door', 'North_Wall'）

2. **寸法設定**: 
   - オブジェクトのサイズ変更は `set_object_dimensions` ツールを使用してください
   - スケール操作による計算ミスを防ぐため、直接的な寸法指定を行います

3. **検証**: 
   - 作業完了後は必ず `validate_object_compliance` で建築基準をチェックしてください
   - 検証失敗の場合は、適切にオブジェクトを修正してください

4. **問題解決**: 
   - 座標ズレや変形の問題が発生した場合は `normalize_object_transform` を使用してください

## 利用可能なツール

- `create_or_update_object`: オブジェクトの作成・更新（重複防止）
- `set_object_dimensions`: 正確な寸法設定
- `validate_object_compliance`: 建築基準の検証
- `get_building_standards`: 建築基準の検索
- `normalize_object_transform`: オブジェクトの正規化
- `execute_blender_code`: 汎用Pythonコード実行
- `get_scene_info`: シーン情報の取得
- `get_viewport_screenshot`: 画面キャプチャ

日本の建築基準法に準拠した3Dモデル作成をサポートします。
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
        f"Target: Blender at {BLENDER_HOST}:{BLENDER_PORT}\n"
        f"Log File: [dim]{logger.get_log_file_path()}[/dim]", # ログファイルの場所を表示
        title="Welcome"
    ))

    # --- [追加] トークン集計用変数 ---
    total_input_tokens = 0
    total_output_tokens = 0
    turn_count = 0

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # ツール読み込み処理 (変更なし)
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

                # --- [変更] メインループを try...finally で囲む ---
                try:
                    while True:
                        console.print("\n[bold cyan]You:[/bold cyan] ", end="")
                        
                        # 入力待ち (Ctrl+C対応)
                        try:
                            user_input = Prompt.ask("")
                        except (KeyboardInterrupt, EOFError):
                            # ここでの中断はループを抜けて finally ブロックへ
                            raise KeyboardInterrupt

                        if user_input.lower() in ['quit', 'exit', 'q']:
                            console.print("[dim]Exiting loop...[/dim]")
                            break

                        if not user_input.strip():
                            continue

                        messages.append({'role': 'user', 'content': user_input})
                        turn_count += 1

                        # AI応答生成
                        with console.status(
                            f"[bold yellow]Thinking with {MODEL_NAME}...[/bold yellow]",
                            spinner="dots"
                        ) as status:
                            
                            # Ollama呼び出し
                            response = ollama.chat(
                                model=MODEL_NAME,
                                messages=messages,
                                tools=ollama_tools,
                            )
                            messages.append(response.message)

                            # --- [追加] トークン数を集計 (初回生成分) ---
                            # OllamaのPythonライブラリのバージョンによっては属性アクセス
                            in_tokens = getattr(response, 'prompt_eval_count', 0) or 0
                            out_tokens = getattr(response, 'eval_count', 0) or 0
                            
                            total_input_tokens += in_tokens
                            total_output_tokens += out_tokens

                            # ログに記録
                            logger.log_event("LLM_USAGE", {
                                "turn": turn_count,
                                "input_tokens": in_tokens,
                                "output_tokens": out_tokens,
                                "total_so_far": total_input_tokens + total_output_tokens
                            })

                            # ツール実行ループ (while)
                            while response.message.tool_calls:
                                status.update("[bold blue]MCPツールを実行中...[/bold blue]")
                                
                                for tool_call in response.message.tool_calls:
                                    fn_name = tool_call.function.name
                                    fn_args = tool_call.function.arguments

                                    # --- [修正] 日本語での実行内容表示 ---
                                    display_msg = get_tool_display_message(fn_name, fn_args)
                                    console.print(f" -> [bold cyan]{display_msg}[/bold cyan]")
                                    
                                    # デバッグ用に実際の関数名も薄く表示しておくと安心です
                                    console.print(f"    [dim](Call: {fn_name})[/dim]")
                                    
                                    # ロガーに記録
                                    logger.log_tool_call(fn_name, fn_args, None) # 結果はまだNone

                                    try:
                                        result = await session.call_tool(fn_name, arguments=fn_args)
                                        tool_output = result.content[0].text

                                        messages.append({
                                            'role': 'tool',
                                            'content': tool_output,
                                        })
                                        
                                        # 結果をログ更新（簡易的）または別途記録
                                        # 今回は新しいイベントとして記録
                                        logger.log_event("TOOL_RESULT", {
                                            "tool": fn_name,
                                            "output_snippet": tool_output[:100]
                                        })

                                        display_output = tool_output[:100].replace('\n', ' ')
                                        console.print(f"    [dim green]Result: {display_output}...[/dim green]")

                                    except Exception as e:
                                        error_msg = f"Error executing tool {fn_name}: {str(e)}"
                                        console.print(f"[bold red]{error_msg}[/bold red]")
                                        messages.append({
                                            'role': 'tool',
                                            'content': error_msg,
                                        })
                                        logger.log_error("TOOL_EXECUTION_ERROR", error_msg)

                                # 推論の続き（Re-Act）
                                status.update("[bold green]Reasoning next step...[/bold green]")
                                response = ollama.chat(
                                    model=MODEL_NAME,
                                    messages=messages,
                                    tools=ollama_tools,
                                )
                                messages.append(response.message)

                                # --- [追加] トークン数を集計 (ツール後の再生成分) ---
                                in_tokens = getattr(response, 'prompt_eval_count', 0) or 0
                                out_tokens = getattr(response, 'eval_count', 0) or 0
                                total_input_tokens += in_tokens
                                total_output_tokens += out_tokens
                                
                                logger.log_event("LLM_USAGE_REASONING", {
                                    "turn": turn_count,
                                    "input_tokens": in_tokens,
                                    "output_tokens": out_tokens
                                })

                            ai_content = response.message.content

                        console.print("\n[bold magenta]AI:[/bold magenta]")
                        if ai_content:
                            console.print(Markdown(ai_content))
                        else:
                            console.print("[dim](No response content)[/dim]")

                except KeyboardInterrupt:
                    console.print("\n[bold yellow]Session interrupted by user (Ctrl+C).[/bold yellow]")
                
                finally:
                    # --- [追加] セッション終了時の集計表示とログ保存 ---
                    
                    # 1. ログファイルへの保存
                    session_stats = {
                        "total_turns": turn_count,
                        "total_input_tokens": total_input_tokens,
                        "total_output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens
                    }
                    logger.log_event("SESSION_END", session_stats)
                    
                    # 2. コンソールへのテーブル表示
                    stats_table = Table(title="Session Token Usage Summary")
                    stats_table.add_column("Metric", style="cyan")
                    stats_table.add_column("Count", style="magenta")
                    
                    stats_table.add_row("Total Turns", str(turn_count))
                    stats_table.add_row("Input Tokens (Prompt)", str(total_input_tokens))
                    stats_table.add_row("Output Tokens (Eval)", str(total_output_tokens))
                    stats_table.add_row("Total Tokens", str(total_input_tokens + total_output_tokens), style="bold green")
                    
                    console.print("\n")
                    console.print(stats_table)
                    console.print(f"[dim]Log saved to: {logger.get_log_file_path()}[/dim]")

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
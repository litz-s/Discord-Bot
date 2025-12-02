# bot.py
import os
import sqlite3
import discord
from discord.ext import commands
from discord import File
from discord.ui import View, Button
from datetime import datetime
import asyncio

# -------------------------
# 設定（環境に合わせて変更）
# -------------------------
TOKEN = os.getenv("STAR_BOT_TOKEN")
PREFIX = "?"
DB_PATH = "database.db"
STORAGE_DIR = "storage"
PAGE_SIZE = 10  # list のページサイズ

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# -------------------------
# DB 初期化
# -------------------------
def init_db():
    os.makedirs(STORAGE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploader_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    # 検索を速くするための index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_keyword ON files(keyword)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_filename ON files(filename)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_uploader ON files(uploader_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_created ON files(created_at)")
    conn.commit()
    conn.close()

init_db()

# -------------------------
# DB ヘルパー
# -------------------------
def insert_file_record(keyword: str, filename: str, uploader_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO files (keyword, filename, uploader_id, created_at) VALUES (?, ?, ?, ?)",
        (keyword, filename, uploader_id, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

def get_files_by_keyword(keyword: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, keyword, filename, uploader_id, created_at FROM files WHERE keyword = ? ORDER BY id ASC", (keyword,))
    rows = cur.fetchall()
    conn.close()
    return rows

def list_all_keywords_ordered():
    # 登録された順（最も古い登録時の id を基準）で一意のキーワードを返す
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT keyword, MIN(id) as first_id
        FROM files
        GROUP BY keyword
        ORDER BY first_id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def search_fuzzy(query: str):
    """
    キーワード / filename / uploader_id / created_at に対して曖昧検索 (LIKE) を行い、マッチした行を返す
    uploader_id に数字が入っていれば ID 検索としてもヒットするよう扱う
    日付は部分一致で YYYY-MM-DD のような形式で検索可能
    """
    q_like = f"%{query}%"
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # uploader_id は数値であればそのまま等価検索（またはLIKE）する
    results = []
    try:
        # 一般的に LIKE は TEXT に対して使うので uploader も文字列化して検索
        cur.execute("""
            SELECT id, keyword, filename, uploader_id, created_at
            FROM files
            WHERE keyword LIKE ?
               OR filename LIKE ?
               OR CAST(uploader_id AS TEXT) LIKE ?
               OR created_at LIKE ?
            ORDER BY id ASC
        """, (q_like, q_like, q_like, q_like))
        results = cur.fetchall()
    finally:
        conn.close()
    return results

# -------------------------
# ユーティリティ: ファイル保存
# -------------------------
def safe_filename(orig_name: str) -> str:
    # タイムスタンプ接頭で衝突を避ける
    timestamp = int(datetime.utcnow().timestamp())
    sanitized = orig_name.replace("/", "_").replace("\\", "_")
    return f"{timestamp}_{sanitized}"

# -------------------------
# Pagination View
# -------------------------
class PaginationView(View):
    def __init__(self, items: list[str], title: str, page_size: int = PAGE_SIZE, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.items = items
        self.title = title
        self.page_size = page_size
        self.page = 0
        # ボタンの初期 enabled 設定は update_buttons() で行う
        self.prev_button = Button(label="◀ 前へ", style=discord.ButtonStyle.secondary)
        self.next_button = Button(label="次へ ▶", style=discord.ButtonStyle.secondary)
        self.prev_button.callback = self.on_prev
        self.next_button.callback = self.on_next
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    def build_embed(self):
        start = self.page * self.page_size
        end = start + self.page_size
        subset = self.items[start:end]
        embed = discord.Embed(title=self.title, description=f"ページ {self.page+1} / {max(1, (len(self.items)-1)//self.page_size+1)}")
        if not subset:
            embed.add_field(name="結果なし", value="-", inline=False)
        else:
            # 表示は "index. キーワード"
            for i, v in enumerate(subset, start=start+1):
                embed.add_field(name=f"{i}.", value=v, inline=False)
        return embed

    async def on_prev(self, interaction: discord.Interaction):
        # 権限チェック: 操作はコマンド実行者に限定したいならここで確認可能
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        else:
            await interaction.response.defer()

    async def on_next(self, interaction: discord.Interaction):
        max_page = (len(self.items)-1)//self.page_size
        if self.page < max_page:
            self.page += 1
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        else:
            await interaction.response.defer()

    async def on_timeout(self):
        # タイムアウトしたらボタンを無効化してメッセージ更新
        for item in self.children:
            item.disabled = True
        # try to edit but ignore failures
        try:
            # find arbitrary message from view? we don't have reference; user interaction will stop working anyway
            pass
        except:
            pass

# -------------------------
# コマンド実装
# -------------------------

@bot.command(name="imp")
async def imp(ctx: commands.Context, keyword: str):
    """
    ?imp <keyword> で添付ファイルを保存
    """
    # 添付チェック
    attachments = ctx.message.attachments
    if not attachments:
        await ctx.reply("❌ 添付ファイルがありません。添付してから再実行してください。")
        return

    saved = 0
    errors = []
    for att in attachments:
        try:
            # ダウンロードし、ストレージに保存
            safe_name = safe_filename(att.filename)
            local_path = os.path.join(STORAGE_DIR, safe_name)
            await att.save(local_path)  # discord.py Attachment.save を使って保存
            # DB 登録は元のファイル名ではなく保存後のローカル名で管理
            insert_file_record(keyword, safe_name, ctx.author.id)
            saved += 1
        except Exception as e:
            errors.append(f"{att.filename}: {e}")

    # コマンドメッセージ自体を削除（権限がない場合は無視）
    try:
        await ctx.message.delete()
    except Exception:
        pass
    
    # 成功メッセージ送信（先に送ると削除される可能性あるが、仕様は「コマンド履歴を削除する」だけなので返信は残す）
    await ctx.send(f"✅ `{keyword}` に {saved} 件を保存しました。")

    if errors:
        await ctx.send("⚠️ 一部保存に失敗しました:\n" + "\n".join(errors))

@bot.command(name="exp")
async def exp(ctx: commands.Context, keyword: str):
    """
    ?exp <keyword> でキーワードに紐づくファイルを送信
    """
    rows = get_files_by_keyword(keyword)
    if not rows:
        await ctx.reply(f"❌ `{keyword}` に紐づくファイルはありません。")
        return

    sent = 0
    too_large = []
    for _id, kw, filename, uploader_id, created_at in rows:
        path = os.path.join(STORAGE_DIR, filename)
        if not os.path.exists(path):
            await ctx.send(f"⚠️ ファイルが見つかりません: `{filename}`")
            continue
        try:
            await ctx.send(file=File(path))
            sent += 1
            # 連続で大きなファイルを送ると速攻で制限にかかるためちょっと待つ
            await asyncio.sleep(0.5)
        except discord.HTTPException as he:
            # 送信失敗のときはサイズ超過などの可能性
            too_large.append(filename)

    # コマンド発行メッセージを削除
    try:
        await ctx.message.delete()
    except Exception:
        pass

    summary = f"✅ `{keyword}` のファイルを {sent} 件送信しました。"
    if too_large:
        summary += "\n⚠️ 送信に失敗したファイル（サイズ制限など）:\n" + "\n".join(too_large)
    await ctx.send(summary)

@bot.command(name="list")
async def list_cmd(ctx: commands.Context):
    """
    ?list でキーワード一覧をページネーション表示
    """
    keywords = list_all_keywords_ordered()
    if not keywords:
        return await ctx.reply("登録されたキーワードはありません。")

    view = PaginationView(keywords, title="登録キーワード一覧", page_size=PAGE_SIZE)
    embed = view.build_embed()
    await ctx.send(embed=embed, view=view)

@bot.command(name="find")
async def find_cmd(ctx: commands.Context, *, query: str):
    """
    ?find <query> -- keyword/filename/uploader_id/created_at をあいまい検索
    """
    rows = search_fuzzy(query)
    if not rows:
        return await ctx.reply("検索結果が見つかりません。")

    # 行ごとに "id: keyword | filename | uploader | date"
    entries = []
    for _id, kw, filename, uploader_id, created_at in rows:
        entries.append(f"【{_id}】 `{kw}` — `{filename}` — <@{uploader_id}> — {created_at}")

    # ページネーションで表示（reuse PaginationView but items are entries lines)
    view = PaginationView(entries, title=f"検索結果: {query}", page_size=PAGE_SIZE)
    embed = view.build_embed()
    await ctx.send(embed=embed, view=view)

@bot.command(name="fsrm")
async def fsrm(ctx: commands.Context, keyword: str):
    """
    ?fsrm <keyword> でDBとストレージのファイルを削除
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT filename FROM files WHERE keyword = ?", (keyword,))
    rows = cur.fetchall()
    
    if not rows:
        await ctx.reply(f"❌ `{keyword}` に紐づくファイルはありません。")
        conn.close()
        return

    deleted_files = 0
    for (filename,) in rows:
        path = os.path.join(STORAGE_DIR, filename)
        try:
            if os.path.exists(path):
                os.remove(path)
                deleted_files += 1
        except Exception as e:
            # 削除できない場合は無視
            await ctx.send(f"⚠️ ファイル削除に失敗: {filename} ({e})")

    # DB からも削除
    cur.execute("DELETE FROM files WHERE keyword = ?", (keyword,))
    conn.commit()
    conn.close()

    await ctx.send(f"🗑 `{keyword}` に紐づく {deleted_files} 件のファイルとDBデータを削除しました。")

    # コマンドメッセージ自体を削除（権限があれば）
    try:
        await ctx.message.delete()
    except Exception:
        pass

# -------------------------
# エラーハンドリング（権限など）
# -------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("引数が不足しています。コマンドの使い方を確認してください。")
        return
    if isinstance(error, commands.CommandInvokeError):
        # 内部例外の根本原因を表示（デバッグ用）
        await ctx.reply(f"コマンド実行中にエラーが発生しました: {error.original}")
        return
    raise error

# -------------------------
# 起動
# -------------------------
bot.run(TOKEN)

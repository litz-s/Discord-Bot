import discord
import os
from discord.ext import commands
from datetime import datetime, timedelta, timezone

TOKEN = os.getenv("CLEANER_BOT_TOKEN")

# -----------------------------
# コマンド実行を許可するユーザーID
# -----------------------------
ALLOWED_USERS = [
    480968489654288387, # me
    951477324388372561 # yuusei
]

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="?", intents=intents)

# -----------------------------
# フラグ記録（チャンネルごと）
# -----------------------------
ffd_flags = {}
ffdu_flags = {}

# -----------------------------
# 全コマンド共通チェック
# -----------------------------
@bot.check
async def global_permission_check(ctx):
    return ctx.author.id in ALLOWED_USERS


# -----------------------------
# メッセージ削除ロジック（共通関数）
# -----------------------------
async def delete_messages(channel, *, user_id=None, limit=None, since_days=None):
    """
    user_id = 特定ユーザーのみ
    limit = 件数
    since_days = 〇日以内
    """

    now = datetime.now(timezone.utc)
    after = None
    if since_days is not None:
        after = now - timedelta(days=since_days)

    count = 0
    async for msg in channel.history(limit=2000, after=after, oldest_first=False):
        if user_id is not None and msg.author.id != user_id:
            continue

        # 14日より前のメッセージはAPI仕様で削除不可
        if (now - msg.created_at).days >= 14:
            continue

        await msg.delete()
        count += 1

        if limit is not None and count >= limit:
            break

    return count


# ===========================================================
#  ?dl コマンド (delete messages)
# ===========================================================

@bot.command()
async def dl(ctx, target, amount: int = None):
    """
    ?dl <userID> → 対象ユーザーの今日のメッセージ全部削除
    ?dl <userID> <件数> → 対象ユーザーの過去14日以内の〇件を削除
    ?dl all → 全ユーザー分（１日分）
    ?dl all <件数> → 全ユーザーの過去１日以内のメッセージのみ件数指定で削除
    """
    channel = ctx.channel

    if target == "all":
        # 全ユーザー削除
        if amount is None:
            deleted = await delete_messages(channel, user_id=None, since_days=1)
            await ctx.send(f"🗑 全ユーザーの今日のメッセージを削除しました（{deleted}件）")
        else:
            deleted = await delete_messages(channel, user_id=None, limit=amount, since_days=1)
            await ctx.send(f"🗑 全ユーザーのメッセージを {deleted}件 削除しました")
        return

    # 特定ユーザー
    try:
        user_id = int(target)
    except:
        return await ctx.reply("ユーザーIDを指定してください。")

    if amount is None:
        # 今日の全メッセージを削除
        deleted = await delete_messages(channel, user_id=user_id, since_days=1)
        await ctx.send(f"🗑 <@{user_id}> の今日のメッセージを削除しました（{deleted}件）")
    else:
        # 件数削除（14日以内制限）
        deleted = await delete_messages(channel, user_id=user_id, limit=amount, since_days=14)
        await ctx.send(f"🗑 <@{user_id}> のメッセージを {deleted}件 削除しました")


# ===========================================================
#  FFD（全ユーザーフラグ）
# ===========================================================

@bot.group()
async def ffd(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.reply("使用方法 : `?ffd create <flag名>` / `?ffd execute <flag名>`")

@ffd.command()
async def create(ctx, flag_name):
    channel_id = ctx.channel.id

    if channel_id not in ffd_flags:
        ffd_flags[channel_id] = {}

    ffd_flags[channel_id][flag_name] = ctx.message.id
    await ctx.reply(f"📌 フラグ `{flag_name}` を作成しました。")

@ffd.command()
async def execute(ctx, flag_name):
    channel = ctx.channel
    channel_id = channel.id

    if channel_id not in ffd_flags or flag_name not in ffd_flags[channel_id]:
        return await ctx.reply("指定したフラグがありません。")

    start_id = ffd_flags[channel_id][flag_name]
    del ffd_flags[channel_id][flag_name]

    count = 0
    async for msg in channel.history(limit=2000, after=discord.Object(id=start_id)):
        if (datetime.now(timezone.utc) - msg.created_at).days < 14:
            await msg.delete()
            count += 1

    await ctx.send(f"🗑 フラグ `{flag_name}` から現在まで {count} 件削除しました。")


# ===========================================================
#  FFDU（特定ユーザーフラグ）
# ===========================================================

@bot.group()
async def ffdu(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.reply("使用方法 : `?ffdu create <userID>` / `?ffdu execute <userID>`")

@ffdu.command()
async def create(ctx, user_id: int):
    channel_id = ctx.channel.id

    if channel_id not in ffdu_flags:
        ffdu_flags[channel_id] = {}

    ffdu_flags[channel_id][user_id] = ctx.message.id

    await ctx.reply(f"📌 ユーザーフラグを作成しました（対象: <@{user_id}>）。")

@ffdu.command()
async def execute(ctx, user_id: int):
    channel = ctx.channel
    channel_id = channel.id

    if channel_id not in ffdu_flags or user_id not in ffdu_flags[channel_id]:
        return await ctx.reply("指定したフラグがありません。")

    start_id = ffdu_flags[channel_id][user_id]
    del ffdu_flags[channel_id][user_id]

    count = 0
    async for msg in channel.history(limit=2000, after=discord.Object(id=start_id)):
        if msg.author.id == user_id and (datetime.now(timezone.utc) - msg.created_at).days < 14:
            await msg.delete()
            count += 1

    await ctx.send(f"🗑 ユーザーフラグ `<@{user_id}>`のメッセージを {count} 件削除しました。")


# ===========================================================
# エラーハンドリング
# ===========================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        return await ctx.reply("❌ このコマンドを使う権限がありません。")
    raise error


bot.run(TOKEN)

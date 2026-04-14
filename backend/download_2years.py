#!/usr/bin/env python3
"""
全市场2年日线数据下载脚本
- 断点续传：跳过已有足够数据的股票
- 频率控制：Tushare 50次/分钟限制
- 后台执行：nohup python3 download_2years.py &
"""

import tushare as ts
import sqlite3
import os
import sys
import time
import json
import signal
from datetime import datetime, timedelta

# ===== 配置 =====
DB_PATH = os.path.join(os.path.dirname(__file__), 'quantweave.db')
ENV_PATH = os.path.join(os.path.dirname(__file__), '.env')
START_DATE = '20240415'  # 2年前
END_DATE = '20260414'    # 最新
TARGET_DAYS = 480        # 约2年交易日(~240天/年)
BATCH_SIZE = 50          # 每批50只
DELAY_PER_STOCK = 1.3    # 每只间隔(秒) → ~46次/分钟 < 50限制
DELAY_BETWEEN_BATCH = 5  # 批次间隔(秒)
STATE_FILE = os.path.join(os.path.dirname(__file__), '.download_state.json')

# 加载环境变量
def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

env = load_env()
TUSHARE_TOKEN = env.get('TUSHARE_TOKEN', '')
if not TUSHARE_TOKEN:
    print("❌ 未找到 TUSHARE_TOKEN，请在 .env 中配置")
    sys.exit(1)

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# 断点续传状态
running = True
def signal_handler(sig, frame):
    global running
    print("\n⏹️ 收到停止信号，安全退出...")
    running = False
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'completed': [], 'failed': [], 'last_batch': 0}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def get_stocks_needing_data(db):
    """找出数据不足的股票"""
    rows = db.execute("""
        SELECT ts_code, COUNT(*) as days 
        FROM stock_daily 
        GROUP BY ts_code 
        HAVING days < ?
    """, (TARGET_DAYS,)).fetchall()
    
    # 也检查stocks表中有但stock_daily中完全没有的
    missing = db.execute("""
        SELECT s.ts_code, 0 
        FROM stocks s 
        WHERE s.ts_code NOT IN (SELECT DISTINCT ts_code FROM stock_daily)
    """).fetchall()
    
    return list(rows) + list(missing)

def download_stock(ts_code, db):
    """下载单只股票的日线数据"""
    try:
        # 先看已有哪些日期范围
        existing = db.execute(
            "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM stock_daily WHERE ts_code=?",
            (ts_code,)
        ).fetchone()
        
        df = pro.daily(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
        
        if df is None or len(df) == 0:
            return False, "无数据"
        
        count = 0
        for _, r in df.iterrows():
            try:
                db.execute('''INSERT OR REPLACE INTO stock_daily 
                    (ts_code, trade_date, open, high, low, close, pre_close, change_pct, vol, amount)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (r['ts_code'], r['trade_date'], r['open'], r['high'], r['low'],
                     r['close'], r['pre_close'], r['pct_chg'], r['vol'], r['amount']))
                count += 1
            except Exception:
                pass
        
        db.commit()
        return True, f"+{count}条(已有{existing[2]}条)"
        
    except Exception as e:
        err_msg = str(e)
        if "频率" in err_msg or "limit" in err_msg.lower():
            return False, "频率限制"
        elif "权限" in err_msg:
            return False, "无权限"
        else:
            return False, err_msg[:50]

def main():
    global running
    
    db = sqlite3.connect(DB_PATH)
    state = load_state()
    completed_set = set(state['completed'])
    
    print("=" * 60)
    print("QuantWeave 全市场2年数据下载")
    print(f"日期范围: {START_DATE} ~ {END_DATE}")
    print(f"目标: 每只≥{TARGET_DAYS}天数据")
    print("=" * 60)
    
    # 找出需要补充的股票
    needs = get_stocks_needing_data(db)
    needs = [(code, days) for code, days in needs if code not in completed_set]
    
    total = len(needs)
    print(f"\n需要补充: {total}只 (已完成: {len(completed_set)}只)")
    
    if total == 0:
        print("✅ 所有股票数据已充足！")
        db.close()
        return
    
    # 按数据量排序：数据越少的越优先
    needs.sort(key=lambda x: x[1])
    
    success = 0
    fail = 0
    skipped = 0
    start_time = time.time()
    
    for i, (ts_code, existing_days) in enumerate(needs):
        if not running:
            break
        
        # 批次间休息
        if i > 0 and i % BATCH_SIZE == 0:
            batch_num = i // BATCH_SIZE
            elapsed = time.time() - start_time
            speed = i / elapsed * 60 if elapsed > 0 else 0
            eta_min = (total - i) / speed if speed > 0 else 0
            print(f"\n--- 批次{batch_num}完成 | 进度{i}/{total} | "
                  f"成功{success} 失败{fail} | "
                  f"速度{speed:.0f}只/分钟 | ETA {eta_min:.0f}分钟 ---")
            time.sleep(DELAY_BETWEEN_BATCH)
        
        ok, msg = download_stock(ts_code, db)
        
        if ok:
            success += 1
            completed_set.add(ts_code)
            if success % 50 == 0:
                state['completed'] = list(completed_set)
                save_state(state)
            if success % 20 == 0 or i < 10:
                print(f"  [{i+1}/{total}] ✅ {ts_code} {msg}")
        elif "频率限制" in msg:
            print(f"  [{i+1}/{total}] ⏳ {ts_code} 频率限制，等待60秒...")
            state['failed'].append({'code': ts_code, 'reason': msg, 'time': datetime.now().isoformat()})
            save_state(state)
            time.sleep(60)
            # 重试一次
            ok2, msg2 = download_stock(ts_code, db)
            if ok2:
                success += 1
                completed_set.add(ts_code)
                print(f"  [{i+1}/{total}] ✅ {ts_code} 重试成功 {msg2}")
            else:
                fail += 1
                print(f"  [{i+1}/{total}] ❌ {ts_code} 重试仍失败 {msg2}")
        elif "无权限" in msg:
            skipped += 1
            completed_set.add(ts_code)  # 跳过不再重试
        else:
            fail += 1
            state['failed'].append({'code': ts_code, 'reason': msg, 'time': datetime.now().isoformat()})
            if fail % 10 == 0:
                save_state(state)
            if fail <= 5 or fail % 50 == 0:
                print(f"  [{i+1}/{total}] ❌ {ts_code} {msg}")
        
        # 频率控制
        time.sleep(DELAY_PER_STOCK)
    
    # 最终保存状态
    state['completed'] = list(completed_set)
    state['last_update'] = datetime.now().isoformat()
    save_state(state)
    
    # 最终统计
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"下载完成!")
    print(f"  总耗时: {elapsed/60:.1f}分钟")
    print(f"  成功: {success}")
    print(f"  失败: {fail}")
    print(f"  跳过(无权限): {skipped}")
    
    # 验证
    final_count = db.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    final_stocks = db.execute("SELECT COUNT(DISTINCT ts_code) FROM stock_daily").fetchone()[0]
    sufficient = db.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT ts_code FROM stock_daily GROUP BY ts_code HAVING COUNT(*) >= {TARGET_DAYS}
        )
    """).fetchone()[0]
    print(f"  总记录: {final_count:,}")
    print(f"  总股票: {final_stocks}")
    print(f"  数据充足(≥{TARGET_DAYS}天): {sufficient}只")
    
    db.close()

if __name__ == '__main__':
    main()

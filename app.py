"""
飞书英超预测机器人（使用本地历史数据）
功能：读取本地2019-2025赛季数据 + Kimi智能分析 + 飞书推送
"""

from flask import Flask, request, jsonify
import requests
import json
import pandas as pd
from datetime import datetime
import os

app = Flask(__name__)

# ========== 配置区域（请修改为你的信息）==========

# 1. Kimi API Key - 从 https://platform.moonshot.cn/ 获取
KIMI_API_KEY = 'sk-brwaTKuNLaDl6KLaiOhZhoE2JgJQT6VgttXujEBckAMfw9oW'

# 2. 飞书应用凭证 - 从飞书开放平台获取
APP_ID = 'cli_a95d1eb8f1b8dceb'
APP_SECRET = 'SgfPqPrVdKmiGO5dnUvkqbbaDutHyUhl'
VERIFICATION_TOKEN = 'N1eHa4tfNBbWkcsXPHdZngvZmI4u8Tbp'

# 3. 本地数据文件路径（请修改为你的实际路径）
# Windows示例: r'C:\Users\YT\Documents\英超2019-2025完整数据.xlsx'
# Mac示例: '/Users/用户名/Documents/英超2019-2025完整数据.xlsx'
DATA_FILE = r'C:\Users\YT\Documents\英超2019-2025完整数据.xlsx'

# ================================================

KIMI_API_URL = 'https://api.moonshot.cn/v1/chat/completions'
access_token = None


def get_access_token():
    """获取飞书访问令牌"""
    global access_token
    url = 'https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal'
    headers = {'Content-Type': 'application/json'}
    data = {'app_id': APP_ID, 'app_secret': APP_SECRET}
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                access_token = result.get('app_access_token')
                return access_token
    except Exception as e:
        print(f"获取access_token失败: {e}")
    return None


def send_message(chat_id, text):
    """发送消息到飞书"""
    if not access_token:
        get_access_token()
    
    url = 'https://open.feishu.cn/open-apis/im/v1/messages'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    data = {
        'receive_id': chat_id,
        'msg_type': 'text',
        'content': json.dumps({'text': text})
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.json()
    except Exception as e:
        print(f"发送消息失败: {e}")
        return None


def load_historical_data():
    """加载本地历史数据"""
    try:
        df = pd.read_excel(DATA_FILE, sheet_name='全部数据')
        df['比赛日期'] = pd.to_datetime(df['比赛日期'], errors='coerce')
        print(f"✓ 数据加载成功: {len(df)} 场比赛")
        return df
    except Exception as e:
        print(f"✗ 数据加载失败: {e}")
        return None


def get_odds_stats(df, odds_type='主胜', min_matches=20):
    """获取赔率区间统计"""
    completed = df[df['主队进球'].notna()].copy()
    
    odds_col = 'Bet365主胜' if odds_type == '主胜' else \
               'Bet365平局' if odds_type == '平局' else 'Bet365客胜'
    
    if odds_col not in completed.columns:
        return {}
    
    stats = {}
    ranges = [
        (1.0, 1.3, '超低赔(1.0-1.3)'),
        (1.3, 1.6, '低赔(1.3-1.6)'),
        (1.6, 2.0, '中低赔(1.6-2.0)'),
        (2.0, 2.5, '中赔(2.0-2.5)'),
        (2.5, 3.5, '中高赔(2.5-3.5)'),
        (3.5, 10.0, '高赔(3.5+)')
    ]
    
    for min_odds, max_odds, label in ranges:
        mask = (completed[odds_col] >= min_odds) & (completed[odds_col] < max_odds)
        matches = completed[mask]
        
        if len(matches) < min_matches:
            continue
        
        total = len(matches)
        
        if odds_type == '主胜':
            wins = len(matches[matches['比赛结果'] == 'H'])
        elif odds_type == '平局':
            wins = len(matches[matches['比赛结果'] == 'D'])
        else:
            wins = len(matches[matches['比赛结果'] == 'A'])
        
        win_rate = wins / total * 100
        avg_odds = matches[odds_col].mean()
        expected_value = (win_rate / 100 * avg_odds) - 1
        
        stats[label] = {
            'total': total,
            'wins': wins,
            'win_rate': round(win_rate, 1),
            'avg_odds': round(avg_odds, 2),
            'expected_value': round(expected_value * 100, 1)
        }
    
    return stats


def find_similar_matches(df, odds, odds_type='主胜', tolerance=0.1):
    """查找历史相似赔率的比赛"""
    odds_col = 'Bet365主胜' if odds_type == '主胜' else \
               'Bet365平局' if odds_type == '平局' else 'Bet365客胜'
    
    completed = df[df['主队进球'].notna()].copy()
    mask = (completed[odds_col] >= odds * (1 - tolerance)) & \
           (completed[odds_col] <= odds * (1 + tolerance))
    
    return completed[mask]


def call_kimi_analysis(match_data, historical_stats, similar_matches):
    """调用Kimi进行比赛分析"""
    headers = {
        'Authorization': f'Bearer {KIMI_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    similar_summary = {}
    if len(similar_matches) > 0:
        home_wins = len(similar_matches[similar_matches['比赛结果'] == 'H'])
        draws = len(similar_matches[similar_matches['比赛结果'] == 'D'])
        away_wins = len(similar_matches[similar_matches['比赛结果'] == 'A'])
        total = len(similar_matches)
        
        similar_summary = {
            'total': total,
            'home_wins': home_wins,
            'draws': draws,
            'away_wins': away_wins,
            'home_rate': round(home_wins / total * 100, 1) if total > 0 else 0,
            'draw_rate': round(draws / total * 100, 1) if total > 0 else 0,
            'away_rate': round(away_wins / total * 100, 1) if total > 0 else 0
        }
    
    prompt = f"""你是一位专业的英超比赛分析师。请基于以下数据进行预测分析：

【比赛信息】
- 比赛：{match_data['home']} vs {match_data['away']}
- 日期：{match_data['date']}
- Bet365赔率：主胜 {match_data['home_odds']} / 平局 {match_data['draw_odds']} / 客胜 {match_data['away_odds']}

【历史数据统计（基于2019-2025赛季数据）】
主胜赔率区间统计：
{json.dumps(historical_stats.get('主胜', {}), ensure_ascii=False, indent=2)}

平局赔率区间统计：
{json.dumps(historical_stats.get('平局', {}), ensure_ascii=False, indent=2)}

客胜赔率区间统计：
{json.dumps(historical_stats.get('客胜', {}), ensure_ascii=False, indent=2)}

【相似赔率历史表现】
{json.dumps(similar_summary, ensure_ascii=False, indent=2)}

请提供以下分析（用中文）：
1. 各结果的概率预测（主胜/平局/客胜），参考历史相似赔率的表现
2. 价值投注判断（赔率是否有价值，即期望值是否为正）
3. 推荐投注方向及详细理由
4. 风险提示
5. 信心指数（1-10分）

格式要求：
=== 比赛分析 ===
概率预测：
- 主胜：X%（理由...）
- 平局：X%（理由...）
- 客胜：X%（理由...）

价值判断：...
推荐：...
风险：...
信心指数：X/10"""

    data = {
        'model': 'moonshot-v1-8k',
        'messages': [
            {'role': 'system', 'content': '你是一位专业的足球比赛分析师，擅长基于历史数据进行赔率分析和预测。'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.3
    }
    
    try:
        response = requests.post(KIMI_API_URL, headers=headers, json=data, timeout=60)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"分析失败，状态码：{response.status_code}"
    except Exception as e:
        return f"分析出错：{str(e)}"


def analyze_match(home_team, away_team, home_odds, draw_odds, away_odds):
    """分析单场比赛"""
    df = load_historical_data()
    if df is None:
        return "数据加载失败，请检查数据文件路径是否正确"
    
    home_stats = get_odds_stats(df, '主胜')
    draw_stats = get_odds_stats(df, '平局')
    away_stats = get_odds_stats(df, '客胜')
    
    historical_stats = {
        '主胜': home_stats,
        '平局': draw_stats,
        '客胜': away_stats
    }
    
    similar_home = find_similar_matches(df, home_odds, '主胜')
    
    match_data = {
        'home': home_team,
        'away': away_team,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'home_odds': home_odds,
        'draw_odds': draw_odds,
        'away_odds': away_odds
    }
    
    analysis = call_kimi_analysis(match_data, historical_stats, similar_home)
    
    return analysis


@app.route('/webhook', methods=['POST'])
def webhook():
    """接收飞书消息"""
    data = request.json
    
    token = data.get('token')
    if token != VERIFICATION_TOKEN:
        return jsonify({'code': 403, 'msg': 'Invalid token'})
    
    if data.get('type') == 'url_verification':
        return jsonify({'challenge': data.get('challenge')})
    
    if data.get('type') == 'event_callback':
        event = data.get('event', {})
        msg_type = event.get('msg_type')
        
        if msg_type == 'text':
            chat_id = event.get('open_chat_id')
            text = event.get('text', '')
            
            if '预测' in text:
                parts = text.split()
                if len(parts) >= 6:
                    home_team = parts[1]
                    away_team = parts[2]
                    try:
                        home_odds = float(parts[3])
                        draw_odds = float(parts[4])
                        away_odds = float(parts[5])
                        
                        send_message(chat_id, f'正在分析 {home_team} vs {away_team}，请稍候...')
                        
                        analysis = analyze_match(home_team, away_team, home_odds, draw_odds, away_odds)
                        
                        reply = f"""=== {home_team} vs {away_team} 预测分析 ===

{analysis}

---
基于2019-2025赛季历史数据分析
由 Kimi AI 提供分析支持"""
                        
                        send_message(chat_id, reply)
                    except ValueError:
                        send_message(chat_id, '赔率格式错误，请使用数字，例如：预测 曼联 利物浦 2.5 3.2 2.8')
                else:
                    send_message(chat_id, '''使用方法：
预测 主队名 客队名 主胜赔率 平局赔率 客胜赔率

例如：预测 曼联 利物浦 2.5 3.2 2.8''')
            
            elif '数据' in text or '统计' in text:
                df = load_historical_data()
                if df is not None:
                    completed = df[df['主队进球'].notna()]
                    reply = f"""📊 数据状态

总比赛数：{len(df)} 场
已完成：{len(completed)} 场
数据范围：2019-2025赛季

数据文件路径：{DATA_FILE}"""
                    send_message(chat_id, reply)
                else:
                    send_message(chat_id, '数据加载失败，请检查数据文件路径')
            
            else:
                send_message(chat_id, '''你好！我是英超预测机器人

我可以基于2019-2025赛季历史数据，帮你分析英超比赛的赔率。

使用方法：
预测 主队名 客队名 主胜赔率 平局赔率 客胜赔率

例如：
预测 曼联 利物浦 2.5 3.2 2.8

其他命令：
数据 - 查看数据状态''')
    
    return jsonify({'code': 0, 'msg': 'success'})


@app.route('/')
def index():
    return '飞书英超预测机器人运行中！使用本地历史数据（2019-2025赛季）'


if __name__ == '__main__':
    print("正在加载历史数据...")
    test_df = load_historical_data()
    if test_df is not None:
        print(f"✓ 数据加载成功，共 {len(test_df)} 场比赛")
    else:
        print(f"✗ 数据加载失败，请检查路径: {DATA_FILE}")
    
    app.run(host='0.0.0.0', port=10000)

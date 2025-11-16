import json
import os # <-- 必须导入
import requests
import datetime
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- 配置区 ---
# !! 密钥将从 GitHub Secrets (环境变量) 中读取 !!
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
NEWS_API_KEY = os.environ.get('NEWS_API_KEY')

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
NEWS_API_URL = "https://newsapi.org/v2/everything"
INDICATORS_FILE = "indicators.json"
SCORES_FILE = "scores-v3.json" # <-- 脚本将创建这个文件

# --- 1. 网络请求与重试 (不变) ---

def create_retry_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"], backoff_factor=1
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session

# --- 2. NewsAPI 数据获取 (不变) ---

def call_news_api(query, api_key, session):
    headers = {"X-Api-Key": api_key}
    params = {
        "q": query, "language": "zh", "pageSize": 10,
        "sortBy": "relevancy", "searchIn": "title,description"
    }
    try:
        response = session.get(NEWS_API_URL, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data['status'] != 'ok': return f"NewsAPI 错误: {data.get('message', '未知错误')}"
        if data['totalResults'] == 0: return "未找到相关新闻。"
        
        summary = ""
        for article in data['articles']:
            summary += f"标题: {article['title']}\n描述: {article.get('description', '无描述')}\n---\n"
        return summary
    except requests.exceptions.RequestException as e:
        print(f"❌ 调用 NewsAPI 失败 (重试后): {e}")
        return "调用 NewsAPI 失败"

def fetch_economic_data(api_key, session):
    print("正在获取经济数据 (NewsAPI)...")
    query = '(台湾 OR 中国) AND (经济 OR 贸易 OR 制裁 OR 供应链 OR 芯片 OR 保险 OR 港口 OR 航运)'
    return call_news_api(query, api_key, session)

def fetch_military_data(api_key, session):
    print("正在获取军事数据 (NewsAPI)...")
    query = '(台湾 OR 中国) AND (军事 OR 演习 OR 解放军 OR 导弹 OR 航母 OR 战机 OR 国防 OR 禁航 OR NOTAM)'
    return call_news_api(query, api_key, session)

def fetch_political_data(api_key, session):
    print("正在获取政治数据 (NewsAPI)...")
    query = '(台湾 OR 中国) AND (外交 OR 政治 OR 美国 OR 日本 OR 警告 OR 撤侨 OR "旅行警告")'
    return call_news_api(query, api_key, session)

def fetch_local_data():
    print("正在获取在地数据 (模拟)...")
    return "厦门本地居民反馈：本周防空警报测试是年度例行测试，超市物资供应充足，未见抢购，社会秩序正常。"

# --- 3. LLM 指标匹配 (不变) ---

def get_triggered_indicators(category, news_text, indicators_list, api_key):
    # ... (此函数内容不变) ...
    category_indicators = [ind for ind in indicators_list if ind['category'] == category]
    if not category_indicators:
        return {"triggered_ids": [], "reasoning": "没有为此类别定义指标。"}

    system_prompt = f"""
    你是一名专业、严谨、客观的情报分析师。你的任务是**只**根据我提供的“新闻情报”来判断是否**明确触发**了“预警指标清单”中的具体信号。
    **规则:**
    1.  **严格匹配:** 只有当新闻**明确**提到了指标中的事件时，才算“触发”。
    2.  **常规 vs 异常:** 必须区分“常规”活动（如例行演习）和“异常”活动（如非例行、大规模）。指标通常指“异常”活动。
    3.  **返回格式:** 你必须返回一个格式严格的 JSON 对象，包含两个键：
        * `triggered_ids`: 一个数组，包含所有被触发指标的 `id` (例如 ["MIL-1", "MIL-3"])。
        * `reasoning`: 一句简短的（20-40字）中文分析理由，总结你的发现。
    """
    user_prompt = f"""
    请分析以下情报：
    **【预警指标清单 ({category})】**
    {json.dumps(category_indicators, indent=2, ensure_ascii=False)}
    **【新闻情报】**
    "{news_text}"
    请根据上述情报，返回你分析的 JSON 结果。
    """
    headers = { "Content-Type": "application/json", "Authorization": f"Bearer {api_key}" }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "response_format": {"type": "json_object"}
    }
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, data=json.dumps(payload), timeout=45)
        response.raise_for_status()
        result_json_str = response.json()['choices'][0]['message']['content']
        analysis = json.loads(result_json_str)
        if 'triggered_ids' in analysis and 'reasoning' in analysis:
            print(f"✅ 类别 '{category}' 分析成功。")
            return analysis
        else:
            raise ValueError("LLM 返回的 JSON 格式不正确。")
    except requests.exceptions.RequestException as e:
        print(f"❌ 调用 DeepSeek API 失败 ({category}): {e}")
        return {"triggered_ids": [], "reasoning": f"调用 DeepSeek API 失败: {e}"}
    except Exception as e:
        print(f"❌ 处理 LLM 响应失败 ({category}): {e}")
        return {"triggered_ids": [], "reasoning": f"处理 LLM 响应失败: {e}"}


# --- 4. 主执行函数 (!! 已更新 !!) ---

def main():
    # !! 关键修复：检查从环境变量读取的密钥 !!
    if not DEEPSEEK_API_KEY:
        print("!!!!!! 警告 !!!!!!")
        print("错误： DEEPSEEK_API_KEY 未设置。请在 GitHub 'Settings > Secrets' 中设置。")
        exit(1) # 退出并报错，让 Action 失败
            
    if not NEWS_API_KEY:
        print("!!!!!! 警告 !!!!!!")
        print("错误： NEWS_API_KEY 未设置。请在 GitHub 'Settings > Secrets' 中设置。")
        exit(1) # 退出并报错，让 Action 失败
        
    # 1. 加载指标“大脑”
    try:
        with open(INDICATORS_FILE, 'r', encoding='utf-8') as f:
            all_indicators = json.load(f)
    except Exception as e:
        print(f"❌ 致命错误: 无法加载指标文件 '{INDICATORS_FILE}'. 错误: {e}")
        exit(1)
        
    print(f"--- 开始执行风险分析 (V4 - 修复 API 密钥) ---")
    print(f"已加载 {len(all_indicators)} 个预警指标。")

    # 2. 获取数据
    news_session = create_retry_session()
    econ_text = fetch_economic_data(NEWS_API_KEY, news_session)
    mil_text = fetch_military_data(NEWS_API_KEY, news_session)
    pol_text = fetch_political_data(NEWS_API_KEY, news_session)
    local_text = fetch_local_data()

    # 3. 将数据发送给 LLM 进行分析
    print("--- 开始调用 DeepSeek LLM 进行指标匹配 ---")
    econ_analysis = get_triggered_indicators("经济金融", econ_text, all_indicators, DEEPSEEK_API_KEY)
    mil_analysis = get_triggered_indicators("军事后勤", mil_text, all_indicators, DEEPSEEK_API_KEY)
    pol_analysis = get_triggered_indicators("政治舆论", pol_text, all_indicators, DEEPSEEK_API_KEY)
    local_analysis = get_triggered_indicators("在地体感(厦门)", local_text, all_indicators, DEEPSEEK_API_KEY)

    # 4. 汇总所有被触发的 ID
    all_triggered_ids = set(econ_analysis['triggered_ids'] + 
                            mil_analysis['triggered_ids'] + 
                            pol_analysis['triggered_ids'] + 
                            local_analysis['triggered_ids'])
    
    # 5. 计算数学模型
    total_weight_possible = sum(ind['weight'] for ind in all_indicators)
    triggered_weight = 0
    triggered_list = []
    
    for ind_id in all_triggered_ids:
        found = next((ind for ind in all_indicators if ind['id'] == ind_id), None)
        if found:
            triggered_weight += found['weight']
            triggered_list.append(found)
            
    final_score = 0
    if total_weight_possible > 0:
        final_score = (triggered_weight / total_weight_possible) * 100
    
    # 6. 准备最终的 JSON 输出
    final_result = {
        "score": round(final_score),
        "total_indicators": len(all_indicators),
        "triggered_indicators_count": len(triggered_list),
        "triggered_indicators": triggered_list,
        "category_reasoning": {
            "econ": econ_analysis['reasoning'],
            "mil": mil_analysis['reasoning'],
            "pol": pol_analysis['reasoning'],
            "local": local_analysis['reasoning']
        },
        "last_updated": datetime.datetime.now().isoformat()
    }

    # 7. 将结果写入 JSON 文件
    try:
        # 这一步是关键，创建 scores-v3.json
        with open(SCORES_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, indent=4, ensure_ascii=False)
        print(f"\n--- 分析完成 ---")
        print(f"✅ 结果已成功保存到 {SCORES_FILE}")
        print(f"总分: {final_score:.0f} / 100")
        print(f"触发了 {len(triggered_list)} 个指标 (总权重 {triggered_weight})。")

    except IOError as e:
        print(f"❌ 写入 {SCORES_FILE} 失败: {e}")
        exit(1)

if __name__ == "__main__":
    main()

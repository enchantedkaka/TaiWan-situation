import json
import os
import requests
import datetime
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- V4 配置区 ---
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
NEWS_API_KEY = os.environ.get('NEWS_API_KEY')

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
NEWS_API_URL = "https://newsapi.org/v2/everything"
INDICATORS_FILE = "indicators.json"
SCORES_FILE = "scores-v3.json" # 我们将读/写同一个文件

# 衰减因子：一个信号如果未被重新触发，其权重每天衰减为昨天的 75%
# 您可以调整这个值 (例如 0.5 = 衰减很快, 0.9 = 衰减很慢)
DECAY_FACTOR = 0.75
# 权重下限：如果一个信号的权重衰减到 1 以下，我们就将其从激活列表中移除
WEIGHT_FLOOR = 1

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
    # TODO: 未来可以考虑让用户在网页上“提交”本地体感
    return "厦门本地居民反馈：本周防空警报测试是年度例行测试，超市物资供应充足，未见抢购，社会秩序正常。"

# --- 3. LLM 指标匹配 (不变) ---

def get_triggered_indicators(category, news_text, indicators_list, api_key):
    category_indicators = [ind for ind in indicators_list if ind['category'] == category]
    if not category_indicators:
        return {"triggered_ids": [], "reasoning": "没有为此类别定义指标。"}
    system_prompt = f"""
    你是一名专业、严谨、客观的情报分析师。你的任务是**只**根据我提供的“新闻情报”来判断是否**明确触发**了“预警指标清单”中的具体信号。
    **规则:**
    1.  **严格匹配:** 只有当新闻**明确**提到了指标中的事件时，才算“触发”。
    2.  **常规 vs 异常:** 必须区分“常规”活动和“异常”活动。指标通常指“异常”活动。
    3.  **返回格式:** 你必须返回一个格式严格的 JSON 对象，包含两个键：
        * `triggered_ids`: 一个数组，包含所有被触发指标的 `id`。
        * `reasoning`: 一句简短的中文分析理由。
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
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
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

# --- 4. 主执行函数 (V4 - 累积衰减逻辑) ---

def main():
    if not DEEPSEEK_API_KEY:
        print("!!!!!! 警告 !!!!!! 缺少 DEEPSEEK_API_KEY。")
        exit(1)
    if not NEWS_API_KEY:
        print("!!!!!! 警告 !!!!!! 缺少 NEWS_API_KEY。")
        exit(1)
        
    # 1. 加载“指标大师列表”
    try:
        with open(INDICATORS_FILE, 'r', encoding='utf-8') as f:
            all_indicators_master = {ind['id']: ind for ind in json.load(f)}
    except Exception as e:
        print(f"❌ 致命错误: 无法加载指标文件 '{INDICATORS_FILE}'. 错误: {e}")
        exit(1)
        
    print(f"--- 开始执行风险分析 (V4 - 累积衰减模型) ---")
    print(f"已加载 {len(all_indicators_master)} 个预警指标。")

    # 2. 加载“昨天的状态”
    today = datetime.now(timezone.utc).date()
    yesterday_state = {}
    try:
        with open(SCORES_FILE, 'r', encoding='utf-8') as f:
            yesterday_data = json.load(f)
            yesterday_state = yesterday_data.get('active_indicators', {})
            print(f"✅ 成功加载昨天的状态，有 {len(yesterday_state)} 个激活的指标。")
    except FileNotFoundError:
        print("ℹ️ 未找到昨天的 scores-v3.json。将从 0 开始计算。")
    except Exception as e:
        print(f"⚠️ 警告: 无法解析昨天的 scores-v3.json。将从 0 开始。错误: {e}")

    # 3. 获取“今天的新闻”
    news_session = create_retry_session()
    econ_text = fetch_economic_data(NEWS_API_KEY, news_session)
    mil_text = fetch_military_data(NEWS_API_KEY, news_session)
    pol_text = fetch_political_data(NEWS_API_KEY, news_session)
    local_text = fetch_local_data()

    # 4. 获取“今天新触发的信号”
    print("--- 开始调用 DeepSeek LLM 进行指标匹配 ---")
    econ_analysis = get_triggered_indicators("经济金融", econ_text, list(all_indicators_master.values()), DEEPSEEK_API_KEY)
    mil_analysis = get_triggered_indicators("军事后勤", mil_text, list(all_indicators_master.values()), DEEPSEEK_API_KEY)
    pol_analysis = get_triggered_indicators("政治舆论", pol_text, list(all_indicators_master.values()), DEEPSEEK_API_KEY)
    local_analysis = get_triggered_indicators("在地体感(厦门)", local_text, list(all_indicators_master.values()), DEEPSEEK_API_KEY)

    today_triggered_ids = set(
        econ_analysis['triggered_ids'] + 
        mil_analysis['triggered_ids'] + 
        pol_analysis['triggered_ids'] + 
        local_analysis['triggered_ids']
    )
    print(f"ℹ️ 今天新触发的指标ID: {today_triggered_ids}")

    # 5. V4 核心：计算“今天的状态”（衰减 + 刷新）
    today_state = {}
    
    # a. 处理昨天的信号（衰减或刷新）
    for ind_id, data in yesterday_state.items():
        if ind_id not in all_indicators_master:
            continue # 如果指标已从 master 中删除，则跳过

        base_weight = all_indicators_master[ind_id]['weight']
        
        if ind_id in today_triggered_ids:
            # 刷新：今天再次触发
            print(f"🔄 刷新指标: {ind_id}")
            today_state[ind_id] = {
                "base_weight": base_weight,
                "current_weight": base_weight, # 权重刷新回 100%
                "triggered_on": str(today)
            }
        else:
            # 衰减：今天未触发
            decayed_weight = data['current_weight'] * DECAY_FACTOR
            if decayed_weight >= WEIGHT_FLOOR:
                print(f"📉 衰减指标: {ind_id} (从 {data['current_weight']:.1f} -> {decayed_weight:.1f})")
                today_state[ind_id] = {
                    "base_weight": base_weight,
                    "current_weight": decayed_weight,
                    "triggered_on": data['triggered_on'] # 保持原始触发日期
                }
            else:
                print(f"❌ 移除指标: {ind_id} (衰减至 {decayed_weight:.1f})")

    # b. 添加今天才出现的新信号
    for ind_id in today_triggered_ids:
        if ind_id not in today_state: # 仅当它不是一个被“刷新”的旧信号时
            if ind_id not in all_indicators_master:
                print(f"⚠️ LLM 触发了一个不存在的 ID: {ind_id}")
                continue
            
            print(f"🔥 新增指标: {ind_id}")
            base_weight = all_indicators_master[ind_id]['weight']
            today_state[ind_id] = {
                "base_weight": base_weight,
                "current_weight": base_weight,
                "triggered_on": str(today)
            }

    # 6. 计算最终总分
    total_possible_weight = sum(ind['weight'] for ind in all_indicators_master.values())
    total_current_weight = sum(data['current_weight'] for data in today_state.values())
    
    final_score = 0
    if total_possible_weight > 0:
        final_score = (total_current_weight / total_possible_weight) * 100
    
    # 7. 准备最终的 JSON 输出
    final_result = {
        "score": round(final_score),
        "total_indicators_possible": len(all_indicators_master),
        "active_indicators_count": len(today_state),
        "active_indicators": today_state, # <-- 关键：保存“状态”
        "category_reasoning": { # <-- 保存 LLM 的“理由”
            "econ": econ_analysis['reasoning'],
            "mil": mil_analysis['reasoning'],
            "pol": pol_analysis['reasoning'],
            "local": local_analysis['reasoning']
        },
        "last_updated": datetime.now(timezone.utc).isoformat()
    }

    # 8. 将结果写入 JSON 文件
    try:
        with open(SCORES_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, indent=4, ensure_ascii=False)
        print(f"\n--- 分析完成 ---")
        print(f"✅ 结果已成功保存到 {SCORES_FILE}")
        print(f"总分: {final_score:.0f} / 100")
        print(f"触发了 {len(today_state)} 个指标 (总权重 {total_current_weight:.1f})。")

    except IOError as e:
        print(f"❌ 写入 {SCORES_FILE} 失败: {e}")
        exit(1)

if __name__ == "__main__":
    main()

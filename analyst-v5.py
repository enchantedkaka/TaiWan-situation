import json
import os
import requests
import feedparser # <-- 新增：用于解析 RSS
import datetime
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- V5 配置区 ---
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
NEWS_API_KEY = os.environ.get('NEWS_API_KEY')

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
NEWS_API_URL = "https://newsapi.org/v2/everything"
INDICATORS_FILE = "indicators.json"
SCORES_FILE = "scores-v3.json"

# 衰减因子 (0.75 表示每天衰减 25%)
DECAY_FACTOR = 0.75
WEIGHT_FLOOR = 1

# --- 1. 网络请求基础 ---

def create_retry_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"], backoff_factor=1
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session

# --- 2. 数据获取模块 ---

# A. 国际/商业新闻 (NewsAPI)
def fetch_newsapi_data(query, api_key, session):
    print(f"🌐 正在调用 NewsAPI 获取: {query}...")
    headers = {"X-Api-Key": api_key}
    params = {
        "q": query, "language": "zh", "pageSize": 10,
        "sortBy": "publishedAt", # 改为按时间排序，获取最新的
        "searchIn": "title,description"
    }
    try:
        response = session.get(NEWS_API_URL, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            return ""
        data = response.json()
        if data.get('totalResults', 0) == 0:
            return ""
        
        summary = ""
        for article in data['articles'][:5]: # 只取前5条
            summary += f"- [NewsAPI] {article['title']} ({article['publishedAt'][:10]})\n"
        return summary
    except Exception as e:
        print(f"⚠️ NewsAPI 调用部分失败: {e}")
        return ""

# B. 中国官方信源 (Google News RSS Hack)
def fetch_official_sources():
    print("🇨🇳 正在监控中国官方信源 (通过 Google RSS)...")
    
    # 定义我们要监控的“垂直领域”
    # site: 语法让我们能精准定位到特定域名的内容
    # when:2d 限制为过去 48 小时，保证时效性
    targets = [
        {
            "name": "外交部/国防部 (官方表态)",
            "query": "site:mfa.gov.cn OR site:mod.gov.cn"
        },
        {
            "name": "解放军报/军网 (军事动向)",
            "query": "site:81.cn OR site:chinamil.com.cn"
        },
        {
            "name": "海事局 (航行警告/演习)",
            "query": "site:msa.gov.cn AND (禁航 OR 演习 OR 实弹)"
        }
    ]
    
    all_official_news = ""
    
    for target in targets:
        # 构造 Google News RSS URL
        # hl=zh-CN&gl=CN&ceid=CN:zh-CN 强制使用简中/中国区结果
        encoded_query = requests.utils.quote(target['query'] + " when:2d")
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-CN&gl=CN&ceid=CN:zh-CN"
        
        try:
            feed = feedparser.parse(rss_url)
            if not feed.entries:
                continue
                
            all_official_news += f"\n【{target['name']}】:\n"
            # 每个信源取前 3 条最新的
            for entry in feed.entries[:3]:
                title = entry.title
                # Google RSS 的 link 通常是跳转链接，我们主要需要标题和摘要
                published = entry.published if 'published' in entry else "未知时间"
                all_official_news += f"- {title} ({published})\n"
                
        except Exception as e:
            print(f"⚠️ RSS 获取失败 ({target['name']}): {e}")
            
    return all_official_news

# --- 3. 综合情报获取函数 ---

def get_combined_intelligence(category, news_api_query, news_api_key, session):
    """
    组合 NewsAPI (国际/商业) 和 Google RSS (官方/垂直) 的情报
    """
    final_text = ""
    
    # 1. 获取 NewsAPI 数据
    news_api_text = fetch_newsapi_data(news_api_query, news_api_key, session)
    if news_api_text:
        final_text += "=== 国际与商业媒体报道 ===\n" + news_api_text + "\n"
    
    # 2. 获取官方信源 (仅对特定类别启用，避免重复请求)
    # 只有“军事”和“政治”类别才需要去查外交部和海事局
    if category in ["军事后勤", "政治舆论"]:
        official_text = fetch_official_sources()
        if official_text:
            final_text += "=== 中国官方与核心信源 (过去48小时) ===\n" + official_text + "\n"
            
    if not final_text:
        return "未获取到相关新闻。"
        
    return final_text

# --- 4. LLM 分析与主逻辑 (与 V4 保持一致，微调了调用方式) ---

def get_triggered_indicators(category, news_text, indicators_list, api_key):
    category_indicators = [ind for ind in indicators_list if ind['category'] == category]
    if not category_indicators:
        return {"triggered_ids": [], "reasoning": "无指标。"}

    system_prompt = f"""
    你是一名情报分析师。请根据提供的【混合情报源】（包含国际媒体和中国官方信源）判断是否**明确触发**了预警指标。
    
    注意：
    1. "官方信源"部分的可信度极高，如果海事局(MSA)发布了禁航令，或者外交部使用了极端措辞，请务必触发对应指标。
    2. 必须区分"例行"与"非例行/大规模"。
    
    请返回 JSON:
    {{ "triggered_ids": ["ID1", "ID2"], "reasoning": "简短分析..." }}
    """
    
    user_prompt = f"""
    **【预警指标 ({category})】**
    {json.dumps(category_indicators, indent=2, ensure_ascii=False)}

    **【混合情报源】**
    "{news_text}"
    """
    
    headers = { "Content-Type": "application/json", "Authorization": f"Bearer {api_key}" }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "response_format": {"type": "json_object"}
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, data=json.dumps(payload), timeout=45)
        result = response.json()['choices'][0]['message']['content']
        return json.loads(result)
    except Exception as e:
        print(f"❌ LLM 分析失败 ({category}): {e}")
        return {"triggered_ids": [], "reasoning": f"分析出错: {e}"}

def main():
    if not DEEPSEEK_API_KEY or not NEWS_API_KEY:
        print("❌ 错误: 缺少 API 密钥。")
        exit(1)

    try:
        with open(INDICATORS_FILE, 'r', encoding='utf-8') as f:
            all_indicators_master = {ind['id']: ind for ind in json.load(f)}
    except Exception as e:
        print(f"❌ 无法加载指标文件: {e}")
        exit(1)

    # 加载昨天状态
    try:
        with open(SCORES_FILE, 'r', encoding='utf-8') as f:
            yesterday_data = json.load(f)
            yesterday_state = yesterday_data.get('active_indicators', {})
    except:
        yesterday_state = {}

    session = create_retry_session()

    # 定义查询关键词
    queries = {
        "经济金融": '(台湾 OR 中国) AND (经济 OR 贸易 OR 制裁 OR 供应链 OR 芯片)',
        "军事后勤": '(台湾 OR 中国) AND (军事 OR 演习 OR 解放军 OR 航母 OR 禁航)',
        "政治舆论": '(台湾 OR 中国) AND (外交 OR 政治 OR 警告 OR 撤侨)',
        "在地体感(厦门)": '厦门 AND (防空 OR 演习 OR 交通管制)' # 依然主要靠模拟或手动，NewsAPI很难抓到这个
    }

    # 执行分析
    results = {}
    print("--- 开始多源情报采集与分析 ---")
    
    # 经济
    text_econ = get_combined_intelligence("经济金融", queries["经济金融"], NEWS_API_KEY, session)
    results["econ"] = get_triggered_indicators("经济金融", text_econ, list(all_indicators_master.values()), DEEPSEEK_API_KEY)
    
    # 军事 (重点增强：官方信源)
    text_mil = get_combined_intelligence("军事后勤", queries["军事后勤"], NEWS_API_KEY, session)
    results["mil"] = get_triggered_indicators("军事后勤", text_mil, list(all_indicators_master.values()), DEEPSEEK_API_KEY)
    
    # 政治 (重点增强：官方信源)
    text_pol = get_combined_intelligence("政治舆论", queries["政治舆论"], NEWS_API_KEY, session)
    results["pol"] = get_triggered_indicators("政治舆论", text_pol, list(all_indicators_master.values()), DEEPSEEK_API_KEY)
    
    # 本地 (保持模拟，或通过 NewsAPI 碰运气)
    # 注意：Google RSS 也可以搜 "site:xiamen.gov.cn" 但通常很难搜到实时民防信息
    text_local = "厦门本地居民反馈：本周防空警报测试是年度例行测试，超市物资供应充足，未见抢购，社会秩序正常。"
    results["local"] = get_triggered_indicators("在地体感(厦门)", text_local, list(all_indicators_master.values()), DEEPSEEK_API_KEY)

    # --- 状态计算 (衰减/刷新) ---
    today_triggered_ids = set()
    for res in results.values():
        today_triggered_ids.update(res.get('triggered_ids', []))
    
    today_state = {}
    today_str = str(datetime.now(timezone.utc).date())

    # 1. 处理旧指标
    for ind_id, data in yesterday_state.items():
        if ind_id not in all_indicators_master: continue
        base_weight = all_indicators_master[ind_id]['weight']
        
        if ind_id in today_triggered_ids:
            # 刷新
            today_state[ind_id] = { "base_weight": base_weight, "current_weight": base_weight, "triggered_on": today_str }
        else:
            # 衰减
            new_weight = data['current_weight'] * DECAY_FACTOR
            if new_weight >= WEIGHT_FLOOR:
                today_state[ind_id] = { "base_weight": base_weight, "current_weight": new_weight, "triggered_on": data['triggered_on'] }

    # 2. 处理新指标
    for ind_id in today_triggered_ids:
        if ind_id not in today_state and ind_id in all_indicators_master:
            base_weight = all_indicators_master[ind_id]['weight']
            today_state[ind_id] = { "base_weight": base_weight, "current_weight": base_weight, "triggered_on": today_str }

    # 3. 计算总分
    total_possible = sum(i['weight'] for i in all_indicators_master.values())
    current_total = sum(i['current_weight'] for i in today_state.values())
    score = (current_total / total_possible) * 100 if total_possible > 0 else 0

    # 4. 保存
    final_data = {
        "score": round(score),
        "total_indicators_possible": len(all_indicators_master),
        "active_indicators_count": len(today_state),
        "active_indicators": today_state,
        "category_reasoning": { k: v['reasoning'] for k, v in results.items() },
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    
    with open(SCORES_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=4, ensure_ascii=False)
    
    print(f"✅ 分析完成。总分: {round(score)}")

if __name__ == "__main__":
    main()

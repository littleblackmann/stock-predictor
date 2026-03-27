import json, sys
sys.path.insert(0, '.')

from data.news_sentiment import NewsSentimentAnalyzer
a = NewsSentimentAnalyzer()
result = a.analyze("0050.TW")
print(f"分析結果: {result}")

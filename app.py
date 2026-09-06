
import os
import json
import base64
import mimetypes
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

AI_BASE_URL = os.getenv("AI_BASE_URL", "").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")

SYSTEM_PROMPT = """
你是一个面向中国留学生的“澳洲留学生AI助手”。

你的任务不是单纯翻译，而是把学生收到的英文邮件、课程页面、学校系统截图、
租房通知、账单或生活办事页面，整理成简单、清楚、可执行的中文建议。

请只输出 JSON，格式必须是：
{
  "importance": "高/中/低",
  "title": "一句话总结",
  "meaning": "这是什么，用简单中文解释",
  "deadline": "明确日期；没有则写'未发现明确截止日期'",
  "actions": ["第一步", "第二步", "第三步"],
  "risk": "如果不处理可能怎样；没有明显风险则说明",
  "reply_needed": true/false,
  "reply_draft": "如果需要回复，给简单自然英文草稿；不需要则为空字符串",
  "uncertainty": "哪些地方你不能确定；没有则写'无明显不确定项'"
}

规则：
1. 不要吓唬学生。
2. 不确定的信息必须明确说不确定，不要编造学校规则。
3. 如果涉及成绩、签证、法律、医疗、付款、合同，只做信息整理和风险提醒，并建议核对官方来源。
4. 中文尽量简单自然，适合英语基础一般的留学生。
5. 如果图片模糊、信息不完整，要明确说明。
"""

def image_to_data_url(file_storage):
    mime = file_storage.mimetype or mimetypes.guess_type(file_storage.filename)[0] or "image/jpeg"
    raw = file_storage.read()
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{encoded}"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    if not AI_BASE_URL or not AI_API_KEY or not AI_MODEL:
        return jsonify({
            "error": "还没有配置 AI。请先在 .env 文件中填写 AI_BASE_URL、AI_API_KEY、AI_MODEL。"
        }), 400

    school = request.form.get("school", "未知学校")
    category = request.form.get("category", "学校邮件 / 课程")
    text = (request.form.get("text") or "").strip()
    image = request.files.get("image")

    if not text and not image:
        return jsonify({"error": "请粘贴文字，或者上传一张截图。"}), 400

    content = []

    prompt_text = f"""
学生学校：{school}
问题类型：{category}

学生补充文字：
{text if text else "无"}

请结合文字和截图（如果有）进行分析。
"""
    content.append({"type": "text", "text": prompt_text})

    if image:
        try:
            data_url = image_to_data_url(image)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": data_url
                }
            })
        except Exception as e:
            return jsonify({"error": "读取图片失败", "detail": str(e)}), 400

    url = f"{AI_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}
        ],
        "response_format": {"type": "json_object"}
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=90)

        if r.status_code >= 400:
            return jsonify({
                "error": f"AI接口返回错误 {r.status_code}",
                "detail": r.text[:1000]
            }), 500

        result = r.json()
        content_text = result["choices"][0]["message"]["content"]

        try:
            parsed = json.loads(content_text)
        except Exception:
            parsed = {
                "importance": "中",
                "title": "AI已返回结果，但格式没有完全解析",
                "meaning": content_text,
                "deadline": "未解析",
                "actions": [],
                "risk": "",
                "reply_needed": False,
                "reply_draft": "",
                "uncertainty": "返回格式异常"
            }

        return jsonify(parsed)

    except Exception as e:
        return jsonify({
            "error": "请求 AI 失败",
            "detail": str(e)
        }), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

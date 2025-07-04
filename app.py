from flask import Flask, render_template_string, request, session, redirect, url_for
import openai
import os

# ====== 설정 ======
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PASSWORD = "1234"  # 접속 비밀번호 설정
# ==================

openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)
app.secret_key = "supersecretkey"  # 세션용

HTML_LOGIN = """
<h2>문제 생성 웹앱</h2>
<form method="post">
    <input type="password" name="pw" placeholder="비밀번호 입력" required>
    <button type="submit">입장</button>
    {% if error %}<p style="color:red;">{{ error }}</p>{% endif %}
</form>
"""

HTML_MAIN = """
<h2>문제 생성 웹앱</h2>
<form method="post">
    <input type="text" name="topic" placeholder="문제 주제 입력" required>
    <button type="submit">문제 생성</button>
</form>
{% if result %}
    <h3>생성된 문제</h3>
    <pre style="white-space: pre-wrap;">{{ result }}</pre>
{% endif %}
<a href="{{ url_for('logout') }}">로그아웃</a>
"""

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("login"):
        return redirect(url_for("main"))
    error = None
    if request.method == "POST":
        if request.form["pw"] == PASSWORD:
            session["login"] = True
            return redirect(url_for("main"))
        else:
            error = "비밀번호가 틀렸습니다."
    return render_template_string(HTML_LOGIN, error=error)

@app.route("/main", methods=["GET", "POST"])
def main():
    if not session.get("login"):
        return redirect(url_for("login"))
    result = None
    if request.method == "POST":
        topic = request.form["topic"]
        prompt = f"""
Create 10 quiz questions about '{topic}'.\nAll questions must be based on the standards and regulations of the Republic of Korea, for food companies, and specifically for HACCP-certified companies.\nQuestions 1-5 must be multiple choice (with 4 options), and questions 6-10 must be short answer.\nFor each question, provide the answer and a brief explanation.\nAll questions must be directly related to the topic.\nAll questions, answers, and explanations must be written in Korean.\nFormat:\n1. (Multiple choice question)\n   1) Option1 2) Option2 3) Option3 4) Option4\n   Answer: (Correct answer)\n   Explanation: (Explanation)\n6. (Short answer question)\n   Answer: (Correct answer)\n   Explanation: (Explanation)\n"""
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.choices[0].message.content
    return render_template_string(HTML_MAIN, result=result)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True) 
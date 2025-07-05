import logging
logging.basicConfig(level=logging.INFO)
logging.info("앱 시작됨 (logging)")
import os
print("GOOGLE_SERVICE_ACCOUNT_KEY:", os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY"))

from flask import Flask, render_template_string, request, session, redirect, url_for, jsonify
import openai
import os
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ====== 설정 ======
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PASSWORD = "1234"  # 접속 비밀번호 설정
GOOGLE_DRIVE_FOLDER_ID = "1U0YMJe4dHRBpYuBpkw0RWGwe0xKP5Kd2"  # 구글 드라이브 폴더 ID
# ==================

# Google API 설정
SCOPES = ['https://www.googleapis.com/auth/forms', 'https://www.googleapis.com/auth/drive']

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
    <div style="margin-top: 20px;">
        <button onclick="createGoogleForm()" style="background-color: #4285f4; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin-right: 10px;">
            구글설문지로 저장
        </button>
        <button onclick="openDriveFolder()" style="background-color: #34a853; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer;">
            저장 폴더 열기
        </button>
    </div>
    <div id="formStatus" style="margin-top: 10px;"></div>
{% endif %}
<a href="{{ url_for('logout') }}">로그아웃</a>

<script>
function createGoogleForm() {
    const statusDiv = document.getElementById('formStatus');
    statusDiv.innerHTML = '구글 설문지 생성 중...';
    
    fetch('/create_form', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            questions: `{{ result | tojson | safe }}`
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            statusDiv.innerHTML = `구글 설문지가 생성되었습니다! <a href="${data.form_url}" target="_blank">설문지 열기</a>`;
        } else {
            statusDiv.innerHTML = '오류: ' + data.error;
        }
    })
    .catch(error => {
        statusDiv.innerHTML = '오류가 발생했습니다: ' + error;
    });
}

function openDriveFolder() {
    window.open('https://drive.google.com/drive/folders/1U0YMJe4dHRBpYuBpkw0RWGwe0xKP5Kd2', '_blank');
}
</script>
"""

def get_google_credentials():
    """Google API 인증 정보를 가져옵니다."""
    try:
        # 서비스 계정 키 JSON을 환경변수에서 가져옵니다
        service_account_info = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
        if service_account_info:
            import json
            service_account_dict = json.loads(service_account_info)
            creds = Credentials.from_service_account_info(
                service_account_dict,
                scopes=SCOPES
            )
            return creds
        else:
            raise Exception("GOOGLE_SERVICE_ACCOUNT_KEY 환경변수가 설정되지 않았습니다.")
    except Exception as e:
        raise Exception(f"Google 인증 설정 오류: {str(e)}")

def parse_questions(text):
    """문제 텍스트를 파싱하여 문제와 보기를 추출합니다."""
    questions = []
    lines = text.split('\n')
    current_question = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 객관식 문제 패턴 (1. 2. 3. 등)
        if re.match(r'^\d+\.', line):
            if current_question:
                questions.append(current_question)
            current_question = {
                'question': line,
                'options': [],
                'type': 'multiple_choice'
            }
        # 보기 패턴 (1) 2) 3) 4) 등)
        elif re.match(r'^\d+\)', line) and current_question:
            current_question['options'].append(line)
        # 주관식 문제 패턴 (8. 9. 10. 등)
        elif re.match(r'^[8-9]\.|^10\.', line):
            if current_question:
                questions.append(current_question)
            current_question = {
                'question': line,
                'type': 'short_answer'
            }
    
    if current_question:
        questions.append(current_question)
    
    return questions

@app.route("/create_form", methods=["POST"])
def create_form():
    try:
        logging.info("1. create_form 진입")
        data = request.get_json()
        questions_text = data.get('questions', '')
        logging.info("2. 받은 questions_text: %s", questions_text)
        
        creds = get_google_credentials()
        logging.info("3. 구글 인증 성공")
        forms_service = build('forms', 'v1', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
        logging.info("4. 구글 서비스 객체 생성 성공")
        
        questions = parse_questions(questions_text)
        logging.info("5. 파싱된 questions: %s", questions)
        
        form = {
            'info': {
                'title': f'문제 시험 - {session.get("current_topic", "주제")}',
                'documentTitle': f'문제 시험 - {session.get("current_topic", "주제")}'
            }
        }
        created_form = forms_service.forms().create(body=form).execute()
        form_id = created_form['formId']
        logging.info("6. 폼 생성 성공, form_id: %s", form_id)
        
        requests = []
        for i, q in enumerate(questions):
            if q['type'] == 'multiple_choice' and q.get('options'):
                request_body = {
                    'createItem': {
                        'item': {
                            'title': q['question'],
                            'questionItem': {
                                'question': {
                                    'choiceQuestion': {
                                        'type': 'RADIO',
                                        'options': [{'value': opt} for opt in q['options']],
                                        'shuffle': False
                                    }
                                }
                            }
                        },
                        'location': {
                            'index': i
                        }
                    }
                }
            else:
                request_body = {
                    'createItem': {
                        'item': {
                            'title': q['question'],
                            'questionItem': {
                                'question': {
                                    'textQuestion': {
                                        'type': 'SHORT_ANSWER'
                                    }
                                }
                            }
                        },
                        'location': {
                            'index': i
                        }
                    }
                }
            requests.append(request_body)
        logging.info("7. 문제 추가 요청 생성 완료")
        
        if requests:
            forms_service.forms().batchUpdate(
                formId=form_id,
                body={'requests': requests}
            ).execute()
            logging.info("8. 폼에 문제 추가 성공")
        
        drive_service.files().update(
            fileId=form_id,
            addParents=GOOGLE_DRIVE_FOLDER_ID,
            removeParents='root'
        ).execute()
        logging.info("9. 폼을 폴더로 이동 성공")
        
        form_url = f"https://docs.google.com/forms/d/{form_id}/edit"
        logging.info("10. 최종 성공, form_url: %s", form_url)
        
        return jsonify({
            'success': True,
            'form_url': form_url,
            'form_id': form_id
        })
        
    except Exception as e:
        logging.error("구글 설문지 생성 오류: %r", e)
        error_msg = str(e) if str(e) else "알 수 없는 오류가 발생했습니다."
        return jsonify({
            'success': False,
            'error': error_msg
        })

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
    error = None
    if request.method == "POST":
        topic = request.form["topic"]
        session["current_topic"] = topic  # 현재 주제를 세션에 저장
        try:
            with open("rules.txt", "r", encoding="utf-8") as f:
                rules = f.read()
            prompt = rules.replace("{topic}", topic)
            # === OpenAI API 호출 부분 주석 처리 ===
            # response = openai_client.chat.completions.create(
            #     model="gpt-4o",
            #     messages=[{"role": "user", "content": prompt}]
            # )
            # result = response.choices[0].message.content
            # === 임시 더미 데이터 ===
            result = f"""{topic}에 대한 예시 문제\n1. {topic}의 정의는 무엇인가요?\n   1) 보기1 2) 보기2 3) 보기3 4) 보기4\n2. {topic}의 주요 특징은 무엇인가요?\n   1) 보기1 2) 보기2 3) 보기3 4) 보기4\n3. {topic}와 관련된 법규는 무엇인가요?\n   1) 보기1 2) 보기2 3) 보기3 4) 보기4\n4. {topic}의 관리 방법은?\n   1) 보기1 2) 보기2 3) 보기3 4) 보기4\n5. {topic}의 중요성은 무엇인가요?\n   1) 보기1 2) 보기2 3) 보기3 4) 보기4\n6. {topic}에 대해 서술하시오.\n7. {topic}의 실제 사례를 설명하시오.\n8. {topic}의 문제점은 무엇인가요?\n9. {topic} 개선 방안을 제시하시오.\n10. {topic} 관련 최신 동향을 설명하시오.\n"""
        except Exception as e:
            error = str(e)
    return render_template_string(HTML_MAIN + "{% if error %}<p style='color:red;'>{{ error }}</p>{% endif %}", result=result, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False) 
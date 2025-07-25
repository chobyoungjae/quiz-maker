## 문제 생성 웹앱

import logging
logging.basicConfig(level=logging.INFO)
logging.info("앱 시작됨 (logging)")
import os
print("GOOGLE_SERVICE_ACCOUNT_KEY:", os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY"))
import base64

# token.pickle 복원 (Render 등 서버 환경)
if os.environ.get("TOKEN_PICKLE_B64") and not os.path.exists("token.pickle"):
    with open("token.pickle", "wb") as f:
        f.write(base64.b64decode(os.environ["TOKEN_PICKLE_B64"]))

from flask import Flask, render_template_string, request, session, redirect, url_for, jsonify
import openai
import os
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# ====== 설정 ======
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PASSWORD = "1234"  # 접속 비밀번호 설정
GOOGLE_DRIVE_FOLDER_ID = "1U0YMJe4dHRBpYuBpkw0RWGwe0xKP5Kd2"  # 구글 드라이브 폴더 ID
# ==================

# Google API 설정
SCOPES = ['https://www.googleapis.com/auth/forms', 'https://www.googleapis.com/auth/drive']

 # openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

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
<form method="post" id="questionForm" onsubmit="return showLoading()">
    <input type="text" name="topic" placeholder="문제 주제 입력" required>
    <button type="submit" id="genBtn">문제 생성</button>
</form>
<div id="loadingMsg" style="color:blue; margin-top:10px; display:none;">문제를 생성중 입니다...</div>
{% if result %}
    <h3>생성된 문제</h3>
    <pre style="white-space: pre-wrap;">{{ display_text }}</pre>
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
function showLoading() {
    document.getElementById('genBtn').disabled = true;
    document.getElementById('loadingMsg').style.display = 'block';
    return true;
}
function createGoogleForm() {
    const statusDiv = document.getElementById('formStatus');
    statusDiv.innerHTML = '구글 설문지 생성 중...';
    
    fetch('/create_form', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            questions: {{ result | tojson | safe }}
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
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

def get_answer_format_from_rules():
    """rules.txt에서 정답/해설 접두사를 읽어옴 (없으면 기본값)"""
    try:
        with open("rules.txt", "r", encoding="utf-8") as f:
            rules_content = f.read()
        import re
        answer_prefix = "정답:"
        explanation_prefix = "해설:"
        # rules.txt에서 첫 번째 정답:, 해설: 접두사 추출
        answer_match = re.search(r"^정답:\s*", rules_content, re.MULTILINE)
        explanation_match = re.search(r"^해설:\s*", rules_content, re.MULTILINE)
        if answer_match:
            answer_prefix = answer_match.group(0).strip()
        if explanation_match:
            explanation_prefix = explanation_match.group(0).strip()
        return answer_prefix, explanation_prefix
    except:
        return "정답:", "해설:"


def parse_questions(text):
    import re as _re
    questions = []
    lines = text.split('\n')
    current_question = None
    in_answer_section = False
    answer_prefix, explanation_prefix = get_answer_format_from_rules()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 하단 요약 구분선 이후는 무시
        if line.startswith('---------------------------'):
            in_answer_section = True
            break
        # 문제 번호로 시작하는 줄이면 새 문제 시작
        m = _re.match(r'^(\d+)\.\s*(.*)', line)
        if m:
            if current_question:
                # 보기가 없으면 주관식으로 설정
                if not current_question['options']:
                    current_question['type'] = 'short_answer'
                questions.append(current_question)
            current_question = {
                'question': line,
                'options': [],
                'type': 'multiple_choice',  # 일단 객관식으로 시작, 보기 없으면 나중에 주관식으로 변경
                'answer': '',
                'explanation': ''
            }
        # 객관식 보기(1), 2), 3), 4))
        elif current_question and _re.match(r'^[1-9]\)', line):
            current_question['options'].append(_re.sub(r'^[1-9]\)\s*', '', line))
        # 정답/해설 (rules.txt에서 읽은 접두사 사용)
        elif current_question and (line.startswith(answer_prefix) or line.startswith(explanation_prefix)):
            if line.startswith(answer_prefix):
                current_question['answer'] = line.replace(answer_prefix, '').strip()
            elif line.startswith(explanation_prefix):
                current_question['explanation'] = line.replace(explanation_prefix, '').strip()
    if current_question:
        if not current_question['options']:
            current_question['type'] = 'short_answer'
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
                # 객관식 문제(보기 있는 것만 추가)
                # 중복 보기 제거
                unique_options = []
                seen = set()
                for opt in q['options']:
                    if opt not in seen:
                        unique_options.append(opt)
                        seen.add(opt)
                request_body = {
                    'createItem': {
                        'item': {
                            'title': q['question'],
                            'questionItem': {
                                'question': {
                                    'choiceQuestion': {
                                        'type': 'RADIO',
                                        'options': [{'value': opt} for opt in unique_options],
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
                requests.append(request_body)
            elif q['type'] == 'short_answer':
                # 주관식 문제
                request_body = {
                    'createItem': {
                        'item': {
                            'title': q['question'],
                            'questionItem': {
                                'question': {
                                    'textQuestion': {
                                        'paragraph': False
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
        logging.info("requests: %s", requests)
        
        if requests:
            forms_service.forms().batchUpdate(
                formId=form_id,
                body={'requests': requests}
            ).execute()
            logging.info("8. 폼에 문제 추가 성공")
        
        # 설문지 생성 후 폴더 이동
        drive_service.files().update(
            fileId=form_id,
            addParents=GOOGLE_DRIVE_FOLDER_ID,
            removeParents='root'
        ).execute()
        logging.info("9. 폼을 폴더로 이동 성공")

        # 정답/해설 txt 파일도 구글 드라이브 폴더에 업로드
        import re as _re
        safe_topic = _re.sub(r'[^\w\d가-힣 _\-]', '', session.get("current_topic", "정답")).strip()
        answer_filename = f"{safe_topic}.txt"
        if os.path.exists(answer_filename):
            file_metadata = {
                'name': answer_filename,
                'parents': [GOOGLE_DRIVE_FOLDER_ID]
            }
            media = None
            try:
                from googleapiclient.http import MediaFileUpload
                media = MediaFileUpload(answer_filename, mimetype='text/plain')
                drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                logging.info(f"정답/해설 txt 파일({answer_filename}) 구글 드라이브 업로드 성공")
            except Exception as e:
                logging.error(f"정답/해설 txt 파일 업로드 실패: {e}")

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
    display_text = None
    error = None
    if request.method == "POST":
        topic = request.form["topic"]
        session["current_topic"] = topic  # 현재 주제를 세션에 저장
        try:
            with open("rules.txt", "r", encoding="utf-8") as f:
                rules = f.read()
            prompt = rules.replace("{topic}", topic)
            # === OpenAI API 호출 ===
            openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048
            )
            print("OpenAI 응답:", response.choices[0].message.content)
            result = response.choices[0].message.content  # 전체(문제+보기+정답+해설+요약)
            # 문제, 해설/정답 분리 저장
            import re as _re
            safe_topic = _re.sub(r'[^\w\d가-힣 _\-]', '', topic).strip()
            answer_filename = f"{safe_topic}.txt"
            # 문제+보기만 화면에 표시
            questions = parse_questions(result)
            display_text = ""
            for q in questions:
                display_text += f"{q['question']}\n"
                if q['options']:
                    for idx, opt in enumerate(q['options'], 1):
                        display_text += f"   {idx}) {opt}\n"
                display_text += "\n"
            # 정답/해설 txt 저장: 1~10번만, 11~20번 등 반복/빈 값/중복 없이 저장
            if result and "---------------------------" in result:
                answer_part = result.split("---------------------------", 1)[1]
                if "정답과 해설 정리:" in answer_part:
                    answer_part = answer_part.split("정답과 해설 정리:", 1)[1]
                answer_part = answer_part.strip()
                # 줄 단위로 읽어서 1~10번까지만 저장
                answer_lines = answer_part.splitlines()
                filtered_lines = []
                count = 0
                for line in answer_lines:
                    # 1~10번 정답/해설만 저장 (빈 줄/빈 값/11번 이상/중복 방지)
                    if count >= 10:
                        break
                    if line.strip() == "" or not re.match(r"^\d+\. ", line):
                        continue
                    filtered_lines.append(line)
                    count += 1
                    # 다음 줄이 해설이면 같이 저장
                    idx = answer_lines.index(line)
                    if idx+1 < len(answer_lines):
                        next_line = answer_lines[idx+1]
                        if next_line.strip().startswith("해설:"):
                            filtered_lines.append(next_line)
                with open(answer_filename, "w", encoding="utf-8") as f:
                    f.write("\n".join(filtered_lines))
            else:
                # fallback: questions에서 1~10번 answer/explanation만 저장
                with open(answer_filename, "w", encoding="utf-8") as f:
                    for idx, q in enumerate(questions[:10], 1):
                        answer = q['answer'] if q['answer'] else ''
                        explanation = q['explanation'] if q['explanation'] else ''
                        if not answer and not explanation:
                            continue
                        f.write(f"{idx}. 정답: {answer}\n   해설: {explanation}\n\n")
        except Exception as e:
            error = str(e)
    return render_template_string(HTML_MAIN + "{% if error %}<p style='color:red;'>{{ error }}</p>{% endif %}", result=result, display_text=display_text, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/quick_form")
def quick_form():
    try:
        creds = get_google_credentials()
        forms_service = build('forms', 'v1', credentials=creds)
        # 최소 폼 생성
        form = {
            'info': {
                'title': '테스트 폼',
                'documentTitle': '테스트 폼'
            }
        }
        created_form = forms_service.forms().create(body=form).execute()
        form_id = created_form['formId']
        form_url = f"https://docs.google.com/forms/d/{form_id}/edit"
        return f"폼 생성 성공! <a href='{form_url}' target='_blank'>폼 열기</a>"
    except HttpError as e:
        import traceback
        tb = traceback.format_exc()
        try:
            content = e.content.decode() if hasattr(e.content, 'decode') else str(e.content)
        except Exception:
            content = str(e.content)
        status = getattr(e, 'resp', None)
        status_code = status.status if status and hasattr(status, 'status') else ''
        return f"폼 생성 실패: {e}<br><b>상세 내용:</b><br><pre>{content}</pre><br><b>HTTP 상태코드:</b> {status_code}<br><pre>{tb}</pre>"
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return f"폼 생성 실패: {e}<br><pre>{tb}</pre>"

# === OAuth 사용자 인증 방식 Google Forms API 테스트 ===
OAUTH_SCOPES = ['https://www.googleapis.com/auth/forms', 'https://www.googleapis.com/auth/drive']

def get_user_credentials():
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', OAUTH_SCOPES)
    creds = flow.run_local_server(port=0)
    return creds

def oauth_create_form():
    creds = get_user_credentials()
    service = build('forms', 'v1', credentials=creds)
    form = {
        'info': {
            'title': 'OAuth 테스트 폼'
        }
    }
    created_form = service.forms().create(body=form).execute()
    print('폼 생성 성공:', created_form['formId'])

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'oauth_test':
        oauth_create_form()
    else:
       # openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=False) 


from fastapi import FastAPI, HTTPException,Request,Form,UploadFile,File
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import pymysql
import bcrypt
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from uuid import uuid4
import re
from pydantic import EmailStr
USERNAME_RE = re.compile(r'^[A-Za-z0-9가-힣]+$')


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key="super-secret-key")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")



conn = pymysql.connect(
    host="localhost",
    user="root",
    password="Wertkmiv5505!",
    database="community_db",
    cursorclass=pymysql.cursors.DictCursor
)
# class UserRegister(BaseModel):
#     username: str
#     email: str
#     password: str
#
# class UserLogin(BaseModel):
#     email: str
#     password: str
# class Post(BaseModel):
#     user_id: int
#     title: str
#     content: str
#
# class CommentCreate(BaseModel):
#     user_id: int
#     post_id: int
#     content: str

@app.post("/users/register")
async def register_user(username: str=Form(...),email:EmailStr=Form(...),password:str=Form(...),password_confirm: str = Form(...),
    avatar: UploadFile | None = File(None),):


    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=400, detail="닉네임은 한글/영문/숫자만 사용 가능합니다. (공백 및 특수문자 불가)")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
    if password !=password_confirm:
        raise HTTPException(status_code=400, detail="Passwords must match")
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s",(str(email),))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        hashed_pw = bcrypt.hashpw(password.encode("utf-8"),bcrypt.gensalt()).decode("utf-8")

        avatar_url=None
        if avatar and avatar.filename:
            if not (avatar.content_type and avatar.content_type.startswith("image/")):
                raise HTTPException(status_code=400, detail="Avatar must be an image file")
            content= await avatar.read()
            if len(content)>5*1024*1024:
                raise HTTPException(status_code=400, detail="Avatar image too large, 5MB is required")
            ext = ""
            if "." in avatar.filename:
                ext = avatar.filename.rsplit(".", 1)[-1].lower()
                if len(ext) > 5:
                    ext = "jpg"
            fname = f"{uuid4().hex}.{ext or 'jpg'}"
            fpath = UPLOAD_DIR / fname
            with open(fpath, "wb") as f:
                f.write(content)
            avatar_url = f"/static/uploads/{fname}"
    try:
        with conn.cursor() as cur:
            cur.execute(
            "INSERT INTO users (username, email, password, avatar_url) VALUES (%s, %s, %s, %s)",
            (username, str(email), hashed_pw, avatar_url)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"message": f"{username}님 회원가입 완료"}

@app.post("/users/login")
def login_user(request: Request,email:str=Form(...),password:str=Form(...)):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s",(email,))
        db_user =cur.fetchone()
        if not db_user:
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
        if not bcrypt.checkpw(password.encode("utf-8"),db_user["password"].encode("utf-8")):
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
        request.session["user"]={"id":db_user["id"], "username":db_user["username"],"email":db_user["email"]}

    return {"message": f"{db_user['username']}님 로그인 성공!"}

@app.get("/users/me")
def get_me(request: Request):
    user=request.session.get("user")
    if not user:
        raise HTTPException(status_code=400,detail="로그인이 필요합니다.")
    with conn.cursor() as cur:
        cur.execute("SELECT avatar_url FROM users WHERE id=%s", (user["id"],))
        row = cur.fetchone()
    return {
        "user": {
                    "username": user["username"],
                    "email": user["email"],
                    "avatar_url": (row or {}).get("avatar_url"),
                }}

@app.post("/users/update")
async def update_user(request: Request,username:str=Form(...),avatar:UploadFile | None=File(None),):

    user=request.session.get("user")
    if not user:
        raise HTTPException(status_code=400, detail="로그인이 필요합니다.")

    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=400,detail="닉네임은 한글/영문/숫자만 사용 가능합니다. (공백 및 특수문자 불가)")

    avatar_url =None
    if avatar and avatar.filename:
        if not (avatar.content_type and avatar.content_type.startswith("image/")):
            raise HTTPException(status_code=400, detail="Avatar must be an image file")
        content= await avatar.read()
        if len(content)>5*1024*1024:
            raise HTTPException(status_code=400, detail="Avatar image too large, 5MB is required")

        ext= avatar.filename.rsplit(".", 1)[-1].lower() if "." in avatar.filename else ""
        if len(ext)>5:
            ext = "jpg"
        fname = f"{uuid4().hex}.{ext or 'jpg'}"
        with open(UPLOAD_DIR / fname, "wb") as f:
            f.write(content)
        avatar_url = f"/static/uploads/{fname}"

    with conn.cursor() as cur:
        if avatar_url is not None:
            cur.execute(
                "UPDATE users SET username = %s, avatar_url = %s WHERE id = %s",
                (username, avatar_url, user["id"])
            )
        else:
            cur.execute(
                "UPDATE users SET username = %s WHERE id = %s",
                (username, user["id"])
            )
        conn.commit()

    # 세션 갱신 (이메일은 이제 건드리지 않음)
    request.session["user"]["username"] = username

    return {"message": "회원정보가 수정되었습니다.", "avatar_url": avatar_url}

def ensure_logged_in(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user

@app.post("/users/change-password")
def change_password(request: Request,old_password: str = Form(...), new_password: str = Form(...)):
    user=request.session.get("user")
    if not user:
        raise HTTPException(status_code=400,detail="로그인이 필요합니다.")
    if len(new_password)<8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")

    with conn.cursor() as cur:
        cur.execute("SELECT password FROM users WHERE id = %s",(user["id"],))
        db_user=cur.fetchone()
        if not db_user:
            raise HTTPException(status_code=404, detail="사용자를 찾을수없습니다.")


        if not bcrypt.checkpw(old_password.encode("utf-8"),db_user["password"].encode("utf-8")):
            raise HTTPException(status_code=401,detail="현재 비밀번호가 올바르지 않습니다.")

        hashed_pw = bcrypt.hashpw(new_password.encode("utf-8"),bcrypt.gensalt()).decode("utf-8")
        cur.execute("UPDATE users SET password = %s WHERE id = %s",(hashed_pw,user["id"]))
        conn.commit()
    return {"message": " 비밀번호가 성공적으로 변경되었습니다."}


@app.post("/users/logout")
def logout(request: Request):
    request.session.pop("user", None)
    return{"message":"로그아웃 되었습니다."}
@app.post("/post")
def create_post(request: Request, title:str=Form(...), content:str=Form(...)):
    user=request.session.get("user")
    if not user:
        raise HTTPException(status_code=400,detail="로그인이 필요합니다.")

    with conn.cursor() as cur:
        cur.execute("INSERT INTO posts (user_id, title, content) VALUES (%s, %s, %s)",(user["id"],title,content))
        conn.commit()
    return{"message":"게시글이 작성되었습니다."}

@app.get("/posts")
def get_posts(request: Request):
    ensure_logged_in(request)
    with conn.cursor() as cur:
        cur.execute("""
                    SELECT p.id, p.title, p.content, u.username, p.created_date
                    FROM posts p
                             JOIN users u ON p.user_id = u.id
                    ORDER BY p.id DESC
                    """)
        rows= cur.fetchall()
    return {"posts":rows}

@app.post("/comment")
def create_comment(request: Request, post_id:int=Form(...),content:str=Form(...)):
    user= request.session.get("user")
    if not user:
        raise HTTPException(status_code=400, detail="로그인이 필요합니다.")
    with conn.cursor() as cur:

        cur.execute("INSERT INTO comments (post_id, user_id, content) VALUES (%s, %s, %s)",
                    (post_id, user["id"], content))
        conn.commit()
    return {"message":"댓글이 등록되었습니다."}


@app.get("/comments/{post_id}")
def get_comments(post_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.id, c.content, u.username, c.created_date
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.post_id = %s
            ORDER BY c.id DESC
        """, (post_id,))
        rows = cur.fetchall()
    return {"comments": rows}
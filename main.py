

from fastapi import FastAPI, HTTPException,Request,Form,UploadFile,File, BackgroundTasks
from transformers import pipeline
from PIL import Image
import torch
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import pymysql
import bcrypt
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from uuid import uuid4
import re
from pydantic import EmailStr
BOT_USER_EMAIL = "assistant@system.local"
BOT_USER_NAME = "AI_assistant"
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

def get_or_create_bot_user_id()-> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (BOT_USER_EMAIL,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO users (username, email, password, avatar_url) VALUES (%s, %s, %s, %s)",
            (BOT_USER_NAME, BOT_USER_EMAIL,
             bcrypt.hashpw(b'bot', bcrypt.gensalt()).decode(),
             "https://cdn-icons-png.flaticon.com/512/4712/4712109.png")
        )
        conn.commit()
        return cur.lastrowid


_CLF = None
def get_image_classifier():
    global _CLF
    if _CLF is None:
        _CLF = pipeline("image-classification", model="microsoft/resnet-50",
                        device=0 if torch.cuda.is_available() else -1)
    return _CLF

def hf_classify_image_to_comment(image_path:str, title:str,content:str)->str:
    try:
        clf=get_image_classifier()
        img=Image.open(image_path).convert("RGB")
        preds=clf(img,top_k=3)
        top=preds[0]
        label=top["label"]
        score=float(top["score"])
        if score>0.35:
            return f"이미지가 '{label}'인가요?"
        else:
            lables=",".join(p["label"] for p in preds)
            return f"헷갈리는데({lables}). 이건가요?"
    except Exception:
        return "이미지 잘 봤습니다!"


def generate_model_comment(post_id: int, image_path:str,title:str, content:str):
    text= hf_classify_image_to_comment(image_path, title, content)
    bot_id=get_or_create_bot_user_id()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO comments (post_id, user_id, content) VALUES (%s, %s, %s)",
            (post_id, bot_id, text))
        conn.commit()

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
@app.post("/users/delete")
def delete_user(request: Request, password:str=Form(...)):
    user=ensure_logged_in(request)
    with conn.cursor() as cur:
        cur.execute("SELECT password FROM users WHERE id=%s", (user["id"],))
        row=cur.fetchone()
        if not row or not bcrypt.checkpw(password.encode("utf-8"),row["password"].encode("utf-8")):
            raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM comments WHERE user_id=%s", (user["id"],))
            cur.execute("DELETE FROM posts WHERE user_id=%s", (user["id"],))
            cur.execute("DELETE FROM users WHERE id=%s", (user["id"],))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    request.session.pop("user",None)
    return {"message": "회원탈퇴가 완료되었습니다."}

@app.get("/users/me")
def get_me(request: Request):
    user=request.session.get("user")
    if not user:
        raise HTTPException(status_code=401,detail="로그인이 필요합니다.")
    with conn.cursor() as cur:
        cur.execute("SELECT avatar_url FROM users WHERE id=%s", (user["id"],))
        row = cur.fetchone()
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "avatar_url": (row or {}).get("avatar_url"),
        }
    }

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
async def create_post(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    content: str = Form(...),
    image: UploadFile | None = File(None),
):
    user = ensure_logged_in(request)

    image_url = None
    saved_path = None

    if image and image.filename:
      if not (image.content_type and image.content_type.startswith("image/")):
          raise HTTPException(status_code=400, detail="이미지 파일만 업로드할 수 있습니다.")
      content_bytes = await image.read()
      if len(content_bytes) > 5 * 1024 * 1024:
          raise HTTPException(status_code=400, detail="이미지 용량은 최대 5MB입니다.")

      ext = ""
      if "." in image.filename:
          ext = image.filename.rsplit(".", 1)[-1].lower()
          if len(ext) > 5:
              ext = "jpg"
      fname = f"{uuid4().hex}.{ext or 'jpg'}"
      fpath = UPLOAD_DIR / fname
      with open(fpath, "wb") as f:
          f.write(content_bytes)
      image_url = f"/static/uploads/{fname}"
      saved_path = str(fpath)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posts (user_id, title, content, image_url) VALUES (%s, %s, %s, %s)",
            (user["id"], title, content, image_url),
        )
        post_id = cur.lastrowid
        conn.commit()
    if saved_path:
        background_tasks.add_task(generate_model_comment,post_id, saved_path,title,content)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, content, image_url, created_date FROM posts WHERE id=%s",
            (post_id,),
        )
        post = cur.fetchone()

    return {"message": "게시글이 작성되었습니다.", "post": post}


@app.get("/posts/{post_id}")
def get_post(post_id:int, request:Request):
    user=ensure_logged_in(request)
    with conn.cursor() as cur:
        cur.execute("""
                    SELECT p.id,
                           p.user_id,
                           p.title,
                           p.content,
                        p.image_url,
                           p.created_date,
                           p.view_count,
                           u.username,
                           u.avatar_url AS author_avatar,
                           IFNULL(lc.cnt, 0)             AS like_count,
                           IFNULL(cc.cnt, 0)             AS comment_count,
                           EXISTS(SELECT 1
                                  FROM likes l2
                                  WHERE l2.post_id = p.id
                                    AND l2.user_id = %s) AS liked
                    FROM posts p
                             JOIN users u ON u.id = p.user_id
                             LEFT JOIN (SELECT post_id, COUNT(*) cnt FROM likes GROUP BY post_id) lc
                                       ON lc.post_id = p.id
                             LEFT JOIN (SELECT post_id, COUNT(*) cnt FROM comments GROUP BY post_id) cc
                                       ON cc.post_id = p.id
                    WHERE p.id = %s
                    """, (user["id"], post_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    return row



# 기존 @app.get("/posts") 함수를 이 코드로 교체
@app.get("/posts")
def get_posts(request: Request, cursor: int | None = None, limit: int = 10):
    user = ensure_logged_in(request)

    # limit 가드 (악성 값 방지)
    limit = max(1, min(int(limit), 30))  # 1~30 사이

    where_sql = ""
    params = [user["id"]]

    # 커서가 있으면 그보다 작은 id만(내림차순 페이징)
    if cursor:
        where_sql = "AND p.id < %s"
        params.append(cursor)

    sql = f"""
        SELECT
          p.id,
          p.title,
          p.content,
          u.username,
          p.image_url,
          u.avatar_url AS author_avatar,
          p.created_date,
          p.view_count,
          IFNULL(lc.cnt, 0)   AS like_count,
          IFNULL(cc.cnt, 0)   AS comment_count,
          EXISTS(
            SELECT 1 FROM likes l2
             WHERE l2.post_id = p.id AND l2.user_id = %s
          )                   AS liked
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN (SELECT post_id, COUNT(*) AS cnt FROM likes GROUP BY post_id) lc ON lc.post_id = p.id
        LEFT JOIN (SELECT post_id, COUNT(*) AS cnt FROM comments GROUP BY post_id) cc ON cc.post_id = p.id
        WHERE 1=1 {where_sql}
        ORDER BY p.id DESC
        LIMIT %s
    """

    # limit+1로 더 가져와서 다음 페이지 유무 판단
    params.append(limit + 1)

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    next_cursor = None
    if len(rows) > limit:
        next_cursor = rows[-1]["id"]  # 다음 요청에서 cursor로 사용
        rows = rows[:-1]              # 초과분 제거

    return {"posts": rows, "next_cursor": next_cursor}


@app.delete("/posts/{post_id}")
def delete_post(request: Request, post_id: int):
    user = ensure_logged_in(request)
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM posts WHERE id = %s", (post_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
        if row["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="본인 글만 삭제할 수 있습니다.")
        cur.execute("DELETE FROM posts WHERE id = %s",(post_id,))
        conn.commit()
    return {"message": "삭제되었습니다."}

@app.post("/posts/{post_id}/like")
def toggle_like(request: Request, post_id:int):
    user=ensure_logged_in(request)
    try:
        with conn.cursor() as cur:
            cur.execute( "INSERT INTO likes (post_id, user_id) VALUES (%s, %s)",
                (post_id, user["id"]))
            conn.commit()
            liked=True

    except pymysql.err.IntegrityError:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM likes WHERE post_id = %s AND user_id = %s",
                (post_id, user["id"])
            )

        conn.commit()
        liked=False
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM likes WHERE post_id = %s", (post_id,))
        like_count = cur.fetchone()["cnt"]
    return {"liked":liked, "like_count":like_count}


@app.post("/posts/{post_id}/view")
def increase_view(post_id:int):
    with conn.cursor() as cur:
        cur.execute("UPDATE posts SET view_count = view_count + 1 WHERE id = %s",(post_id,))
        cur.execute("SELECT view_count FROM posts WHERE id=%s", (post_id,))
        vc = cur.fetchone()["view_count"]
    conn.commit()
    return{"view_count":vc}
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
            SELECT c.id,c.user_id, c.content, u.username,u.avatar_url AS author_avatar, c.created_date
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.post_id = %s
            ORDER BY c.id DESC
        """, (post_id,))
        rows = cur.fetchall()
    return {"comments": rows}

@app.delete("/comments/{comment_id}")
def delete_comment(request: Request, comment_id:int):
    user=ensure_logged_in(request)
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM comments WHERE id = %s", (comment_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
        if row["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="본인 댓글만 삭제할 수 있습니다.")

        cur.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
        conn.commit()
    return {"message":"댓글이 삭제되었습니다."}

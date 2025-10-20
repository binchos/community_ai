from fastapi import FastAPI, HTTPException,Request,Form
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import pymysql
import bcrypt
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key="super-secret-key")
app.mount("/static",StaticFiles(directory="static",html=True), name="static")



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
def register_user(username: str=Form(...),email:str=Form(...),password:str=Form(...)):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s",(email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        hashed_pw = bcrypt.hashpw(password.encode("utf-8"),bcrypt.gensalt())


        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, hashed_pw.decode("utf-8"))
        )
        conn.commit()
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
    return{"user":user}


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
def get_posts():
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
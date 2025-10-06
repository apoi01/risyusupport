import sqlite3
from pathlib import Path
from flask import Flask, g, request, redirect, url_for, flash, render_template_string
import pandas as pd
import unicodedata
from jinja2 import DictLoader

# ==========================
# 基本設定
# ==========================
APP_TITLE = "履修登録サポート"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
CSV_PATHS = [
    DATA_DIR / "keiei_class_complete.csv",
    DATA_DIR / "keizai_class_complete.csv",
    DATA_DIR / "pankyo_class_complete.csv",
]

app = Flask(__name__)
app.secret_key = "change-this-in-production"

# ==========================
# ユーティリティ
# ==========================
def z2h(s: str) -> str:
    """全角→半角 (NFKC) 正規化。None/空はそのまま返す"""
    return unicodedata.normalize("NFKC", s) if s else s

def get_db():
    DATA_DIR.mkdir(exist_ok=True)
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# ==========================
# スキーマ
# ==========================
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    講義名 TEXT NOT NULL,
    時間割コード TEXT UNIQUE,
    開講時期 TEXT,
    担当教員 TEXT,
    開講学部 TEXT,
    曜日時限 TEXT,
    評価方法 TEXT
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    UNIQUE(course_id)
);

CREATE INDEX IF NOT EXISTS idx_courses_fac ON courses(開講学部);
CREATE INDEX IF NOT EXISTS idx_courses_term ON courses(開講時期);
CREATE INDEX IF NOT EXISTS idx_courses_slot ON courses(曜日時限);
"""

# ==========================
# CSV → DB 初期投入
# ==========================
def init_db_and_seed():
    db = get_db()
    db.executescript(SCHEMA_SQL)

    required = ["講義名", "時間割コード", "開講時期", "担当教員", "開講学部", "曜日時限", "評価方法"]

    for path in CSV_PATHS:
        if not path.exists():
            print(f"[WARN] CSVが見つかりません: {path}")
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="utf-8-sig")

        # 必要列の補完と順序調整
        for col in required:
            if col not in df.columns:
                df[col] = ""
        df = df[required]

        # 全角→半角など軽く正規化
        for col in ["講義名", "担当教員", "開講学部", "開講時期", "曜日時限", "評価方法"]:
            df[col] = df[col].astype(str).map(z2h)

        # 挿入（時間割コードのユニーク制約で重複は無視）
        db.executemany(
            """
            INSERT OR IGNORE INTO courses
            (講義名,時間割コード,開講時期,担当教員,開講学部,曜日時限,評価方法)
            VALUES (?,?,?,?,?,?,?)
            """,
            df.values.tolist(),
        )

    db.commit()

# ==========================
# テンプレート
# ==========================
BASE_HTML = """
<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or 'アプリ' }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { background: #f7f9fc; }
      .navbar-brand { font-weight: 700; }
      .card { border: 0; box-shadow: 0 6px 18px rgba(0,0,0,.06); border-radius: 1rem; }
      .chip { padding: .25rem .5rem; border-radius: 999px; background: #eef2ff; font-size: .8rem; }
      .muted { color: #6c757d; }
      .btn-rounded { border-radius: 999px; }
      .container-narrow { max-width: 1100px; }
      .sticky-filter { position: sticky; top: 1rem; }
      .kbd { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; background:#f1f3f5; border-radius:.5rem; padding:.1rem .4rem; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg bg-white border-bottom">
      <div class="container container-narrow">
        <a class="navbar-brand" href="{{ url_for('index') }}">{{ app_title }}</a>
        <ul class="navbar-nav ms-auto">
          <li class="nav-item"><a class="nav-link{% if active=='index' %} active{% endif %}" href="{{ url_for('index') }}">講義一覧</a></li>
          <li class="nav-item"><a class="nav-link{% if active=='mypage' %} active{% endif %}" href="{{ url_for('mypage') }}">マイページ</a></li>
        </ul>
      </div>
    </nav>

    <main class="container container-narrow my-4">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="alert alert-info">{{ messages[0] }}</div>
        {% endif %}
      {% endwith %}
      {% block content %}{% endblock %}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

INDEX_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row g-4">
  <div class="col-lg-4">
    <div class="card p-3 sticky-filter">
      <h5 class="mb-3">検索フィルタ</h5>
      <form method="get" action="{{ url_for('index') }}">
        <div class="mb-3">
          <label class="form-label">キーワード（講義名/教員/評価）</label>
          <input type="text" name="q" value="{{ request.args.get('q','') }}" class="form-control" placeholder="例: マーケ/鈴木/レポート">
        </div>

        <div class="mb-3">
          <label class="form-label">開講学部</label>
          <select class="form-select" name="faculty">
            <option value="">すべて</option>
            {% for f in faculties %}
              <option value="{{ f }}" {% if request.args.get('faculty')==f %}selected{% endif %}>{{ f }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="mb-3">
          <label class="form-label">開講時期</label>
          <select class="form-select" name="term">
            <option value="">すべて</option>
            {% for t in terms %}
              <option value="{{ t }}" {% if request.args.get('term')==t %}selected{% endif %}>{{ t }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="mb-3">
          <label class="form-label">曜日</label>
          <select class="form-select" name="weekday">
            {% set weekdays = ['', '月', '火', '水', '木', '金', '土', '日'] %}
            {% for w in weekdays %}
              <option value="{{ w }}" {% if request.args.get('weekday','')==w %}selected{% endif %}>
                {{ w if w else 'すべて' }}
              </option>
            {% endfor %}
          </select>
        </div>

        <div class="mb-3">
          <label class="form-label">時限（任意）</label>
          <input type="text" name="period" value="{{ request.args.get('period','') }}" class="form-control" placeholder="例: 3 / 3-4 / 3限">
          <div class="form-text">曜日のみ指定でもOK。曜日＋時限の併用でさらに絞り込み。</div>
        </div>

        <div class="d-grid gap-2">
          <button class="btn btn-primary btn-rounded" type="submit">検索</button>
          <a href="{{ url_for('index') }}" class="btn btn-outline-secondary btn-rounded">リセット</a>
        </div>
      </form>
    </div>
  </div>

  <div class="col-lg-8">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h5 class="mb-0">検索結果 <span class="chip">{{ total }} 件</span></h5>
      <form method="post" action="{{ url_for('bulk_fav') }}">
        <input type="hidden" name="ids" id="bulkIds">
        <button class="btn btn-outline-primary btn-sm btn-rounded" type="submit" onclick="collectSelected()">選択した講義をマイページへ追加</button>
      </form>
    </div>

    {% if courses %}
      {% for c in courses %}
        <div class="card p-3 mb-3">
          <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
            <div>
              <h6 class="mb-1">{{ c['講義名'] }} <span class="muted">（{{ c['時間割コード'] }}）</span></h6>
              <div class="small muted">{{ c['担当教員'] }} / {{ c['開講学部'] }} / {{ c['開講時期'] }} / {{ c['曜日時限'] or '—' }}</div>
              {% if c['評価方法'] %}<div class="mt-1"><span class="chip">評価: {{ c['評価方法'] }}</span></div>{% endif %}
            </div>
            <div class="d-flex align-items-center gap-2">
              <div class="form-check">
                <input class="form-check-input" type="checkbox" value="{{ c['id'] }}" id="chk{{ c['id'] }}">
                <label class="form-check-label" for="chk{{ c['id'] }}">選択</label>
              </div>
              {% if c['is_fav'] %}
                <form method="post" action="{{ url_for('unfavorite', course_id=c['id']) }}">
                  <button class="btn btn-outline-secondary btn-sm btn-rounded" type="submit">マイページから外す</button>
                </form>
              {% else %}
                <form method="post" action="{{ url_for('favorite', course_id=c['id']) }}">
                  <button class="btn btn-primary btn-sm btn-rounded" type="submit">マイページに追加</button>
                </form>
              {% endif %}
            </div>
          </div>
        </div>
      {% endfor %}
    {% else %}
      <div class="alert alert-light border">一致する講義がありませんでした。</div>
    {% endif %}
  </div>
</div>

<script>
function collectSelected(){
  const ids = Array.from(document.querySelectorAll('input[type="checkbox"]:checked")).map(el=>el.value);
  document.getElementById('bulkIds').value = ids.join(',');
}
</script>
{% endblock %}
"""

MYPAGE_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h5 class="mb-0">マイページ <span class="chip">{{ total }} 件</span></h5>
  <form method="post" action="{{ url_for('clear_favs') }}" onsubmit="return confirm('マイページの講義をすべて外します。よろしいですか？');">
    <button class="btn btn-outline-danger btn-sm btn-rounded" type="submit">すべて外す</button>
  </form>
</div>

{% if courses %}
  {% for c in courses %}
    <div class="card p-3 mb-3">
      <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
        <div>
          <h6 class="mb-1">{{ c['講義名'] }} <span class="muted">（{{ c['時間割コード'] }}）</span></h6>
          <div class="small muted">{{ c['担当教員'] }} / {{ c['開講学部'] }} / {{ c['開講時期'] }} / {{ c['曜日時限'] or '—' }}</div>
          {% if c['評価方法'] %}<div class="mt-1"><span class="chip">評価: {{ c['評価方法'] }}</span></div>{% endif %}
        </div>
        <form method="post" action="{{ url_for('unfavorite', course_id=c['id']) }}">
          <button class="btn btn-outline-secondary btn-sm btn-rounded" type="submit">外す</button>
        </form>
      </div>
    </div>
  {% endfor %}
{% else %}
  <div class="alert alert-light border">マイページにまだ講義がありません。<a href="{{ url_for('index') }}">講義一覧</a>から追加してください。</div>
{% endif %}
{% endblock %}
"""

# ==========================
# ルーティング
# ==========================
@app.before_request
def _before():
    # 毎リクエストでスキーマは確実に存在させる
    get_db().executescript(SCHEMA_SQL)

@app.before_first_request
def _init_once():
    # デプロイ直後の最初のリクエストで一度だけCSV→DB投入
    with app.app_context():
        init_db_and_seed()

@app.route("/")
def index():
    db = get_db()

    # クエリパラメータ（正規化）
    q       = z2h(request.args.get("q", "").strip())
    faculty = request.args.get("faculty", "").strip()
    term    = request.args.get("term", "").strip()
    weekday = request.args.get("weekday", "").strip()
    period  = z2h(request.args.get("period", "").strip())

    # period の表記ゆれ吸収
    if period.endswith("限"):
        period = period[:-1]
    period = period.replace("－","-").replace("—","-").replace("–","-")

    where = []
    params = []

    if q:
        like = f"%{q}%"
        where.append("(講義名 LIKE ? OR 担当教員 LIKE ? OR 評価方法 LIKE ?)")
        params += [like, like, like]

    if faculty:
        where.append("開講学部 = ?")
        params.append(faculty)

    if term:
        where.append("開講時期 = ?")
        params.append(term)

    if weekday:
        where.append("曜日時限 LIKE ?")
        params.append(f"{weekday}%")

    if period:
        where.append("曜日時限 LIKE ?")
        params.append(f"%{period}%")

    sql = "SELECT * FROM courses"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY 開講学部, 開講時期, 曜日時限, 講義名"

    courses = list(db.execute(sql, params).fetchall())

    # お気に入り判定を付与
    fav_ids = {r[0] for r in db.execute("SELECT course_id FROM favorites").fetchall()}
    enriched = []
    for c in courses:
        d = dict(c)
        d["is_fav"] = c["id"] in fav_ids
        enriched.append(d)

    # プルダウン選択肢
    faculties = [r[0] for r in db.execute("SELECT DISTINCT 開講学部 FROM courses WHERE 開講学部 <> '' ORDER BY 開講学部").fetchall()]
    terms     = [r[0] for r in db.execute("SELECT DISTINCT 開講時期 FROM courses WHERE 開講時期 <> '' ORDER BY 開講時期").fetchall()]

    return render_template_string(
        INDEX_HTML,
        title=f"{APP_TITLE}｜講義一覧",
        app_title=APP_TITLE,
        active="index",
        courses=enriched,
        faculties=faculties,
        terms=terms,
        total=len(enriched),
    )

@app.route("/favorite/<int:course_id>", methods=["POST"])
def favorite(course_id):
    db = get_db()
    try:
        db.execute("INSERT OR IGNORE INTO favorites(course_id) VALUES (?)", (course_id,))
        db.commit()
        flash("マイページに追加しました。")
    except Exception as e:
        flash(f"追加に失敗しました: {e}")
    return redirect(request.referrer or url_for("index"))

@app.route("/unfavorite/<int:course_id>", methods=["POST"])
def unfavorite(course_id):
    db = get_db()
    db.execute("DELETE FROM favorites WHERE course_id=?", (course_id,))
    db.commit()
    flash("マイページから外しました。")
    return redirect(request.referrer or url_for("mypage"))

@app.route("/bulk-fav", methods=["POST"])
def bulk_fav():
    ids = request.form.get("ids", "").strip()
    if not ids:
        flash("講義が選択されていません。")
        return redirect(url_for("index"))
    id_list = [int(x) for x in ids.split(",") if x.isdigit()]
    db = get_db()
    db.executemany("INSERT OR IGNORE INTO favorites(course_id) VALUES (?)", [(i,) for i in id_list])
    db.commit()
    flash(f"{len(id_list)}件をマイページに追加しました。")
    return redirect(url_for("mypage"))

@app.route("/mypage")
def mypage():
    db = get_db()
    rows = db.execute(
        """
        SELECT c.* FROM courses c
        JOIN favorites f ON f.course_id = c.id
        ORDER BY 開講学部, 開講時期, 曜日時限, 講義名
        """
    ).fetchall()
    return render_template_string(
        MYPAGE_HTML,
        title=f"{APP_TITLE}｜マイページ",
        app_title=APP_TITLE,
        active="mypage",
        courses=rows,
        total=len(rows),
    )

@app.route("/clear-favs", methods=["POST"])
def clear_favs():
    db = get_db()
    db.execute("DELETE FROM favorites")
    db.commit()
    flash("マイページを空にしました。")
    return redirect(url_for("mypage"))

# ==========================
# Jinja ローダ登録
# ==========================
app.jinja_loader = DictLoader({
    "base.html": BASE_HTML,
    "index.html": INDEX_HTML,
    "mypage.html": MYPAGE_HTML,
})

# ==========================
# 起動（ローカルのみ）
# ==========================
if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    with app.app_context():
        init_db_and_seed()
    print("== 起動 ==> http://127.0.0.1:5000")
    app.run(debug=True)

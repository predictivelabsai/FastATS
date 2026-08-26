"""FastHTML routes for the FastATS recruiter and public career surfaces."""
from __future__ import annotations

import json
from urllib.parse import quote

import uvicorn
from fasthtml.common import (
    A, Article, Aside, Button, Div, Form, H1, H2, H3, H4, Header, Input, Label,
    Li, Main, Meta, Nav, Option, P, Pre, Script, Section, Select, Small, Span, Style,
    Table, Tbody, Td, Textarea, Th, Thead, Title, Tr, Ul, fast_app,
)
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from agents import content
from agents.recruiter import RecruiterContext, extract_artifact
from agents.turn import stream_turn
from analytics import AnalyticsService
from ats import ATSService
from auth import authenticate, google_identity
from web import google_auth
from chat import ChatService
from config import settings
from crm import CRMService
from database import get_database
from documents import extract_text
from interviews import InterviewService
from seed import build
from semantic import search_candidates
from skills_service import SkillsService
from storage import get_storage

CSS = """
:root{--ink:#1e1d2b;--muted:#6d6a7d;--line:#e5e3ec;--panel:#fff;--bg:#f7f7fb;--brand:#5145cd;--soft:#eeecff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,sans-serif}
a{color:inherit;text-decoration:none}button,.button{border:0;border-radius:8px;background:var(--brand);color:#fff;padding:.65rem .9rem;font-weight:650;cursor:pointer}
button.secondary,.button.secondary{background:#fff;color:var(--ink);border:1px solid var(--line)}input,textarea,select{width:100%;padding:.7rem;border:1px solid #d9d6e2;border-radius:8px;background:#fff;font:inherit}textarea{min-height:120px}label{display:grid;gap:.35rem;font-weight:600;margin:.7rem 0}.shell{display:grid;grid-template-columns:220px 1fr;min-height:100vh}.sidebar{background:#19182a;color:#e9e8f5;padding:1.25rem}.brand{font-size:1.25rem;font-weight:800;margin-bottom:1.5rem}.sidebar a{display:block;padding:.65rem .75rem;border-radius:8px;color:#c9c6dd}.sidebar a:hover{background:#292741;color:#fff}.content{padding:2rem;max-width:1500px;width:100%;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem}.top h1{margin:0}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:1rem;box-shadow:0 1px 2px #1111}.metric{font-size:2rem;font-weight:800}.pipeline{display:grid;grid-template-columns:repeat(6,minmax(220px,1fr));gap:.8rem;overflow-x:auto;padding-bottom:1rem}.column{background:#eeedf4;border-radius:12px;padding:.7rem;min-height:240px}.column h3{display:flex;justify-content:space-between;margin:.3rem}.candidate{background:#fff;border:1px solid var(--line);border-radius:9px;padding:.75rem;margin:.65rem 0}.candidate form{margin-top:.65rem}.pill{display:inline-block;border-radius:999px;background:var(--soft);color:#4338a8;padding:.2rem .55rem;font-size:.8rem}.career{max-width:850px;margin:0 auto;padding:2rem}.career header{display:flex;justify-content:space-between;align-items:center}.split{display:grid;grid-template-columns:2fr 1fr;gap:1rem}.flash{padding:.8rem;border-radius:8px;background:#e9f8ef;color:#175d34}.danger{background:#fff0f0;color:#9b2424}.activity{border-left:2px solid var(--line);padding-left:1rem}.activity li{margin:.6rem 0}@media(max-width:850px){.shell{grid-template-columns:1fr}.sidebar{display:none}.grid,.split{grid-template-columns:1fr}.content{padding:1rem}}
.sidebar a.primary{background:var(--brand);color:#fff;font-weight:700;margin-bottom:.5rem}
.chatwrap{display:grid;grid-template-columns:1fr 380px;height:100vh}
.chatmain{display:flex;flex-direction:column;height:100vh;background:var(--bg)}
.chathead{padding:1rem 1.5rem;border-bottom:1px solid var(--line);background:#fff;display:flex;justify-content:space-between;align-items:center}
.stream{flex:1;overflow-y:auto;padding:1.5rem;display:flex;flex-direction:column;gap:1rem}
.msg{max-width:760px;padding:.85rem 1.05rem;border-radius:14px;white-space:pre-wrap;line-height:1.5}
.msg.user{align-self:flex-end;background:var(--brand);color:#fff;border-bottom-right-radius:4px}
.msg.assistant{align-self:flex-start;background:#fff;border:1px solid var(--line);border-bottom-left-radius:4px}
.msg.tool{align-self:flex-start;background:transparent;color:var(--muted);font-size:.85rem;padding:.2rem .4rem}
.composer{border-top:1px solid var(--line);background:#fff;padding:1rem 1.5rem;display:flex;gap:.6rem}
.composer textarea{min-height:52px;max-height:180px;resize:none}
.canvas{border-left:1px solid var(--line);background:#fff;overflow-y:auto;padding:1.25rem}
.canvas h3{margin-top:0}
.acard{border:1px solid var(--line);border-radius:11px;padding:.85rem;margin-bottom:.8rem}
.acard h4{margin:.1rem 0 .5rem}
.empty{color:var(--muted);text-align:center;margin-top:3rem}
.suggest{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem}
.suggest button{background:#fff;color:var(--ink);border:1px solid var(--line);font-weight:500}
.threadlist a{font-size:.9rem;padding:.5rem .6rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(max-width:900px){.chatwrap{grid-template-columns:1fr}.canvas{display:none}}
"""

db = get_database()
db.migrate()
build(db)
ats = ATSService(db)
crm = CRMService(db)
interviews = InterviewService(db)
analytics = AnalyticsService(db)
chat = ChatService(db)
skills = SkillsService(db)
storage = get_storage()
app, rt = fast_app(live=False, pico=False, secret_key=settings.secret,
                   hdrs=[Title("FastATS"), Meta(name="viewport", content="width=device-width,initial-scale=1"), Style(CSS)])


def shell(session, active: str, *content):
    user = session.get("identity", {})
    nav = [("Dashboard", "/dashboard"), ("Jobs", "/jobs"), ("Candidates", "/candidates"),
           ("Search", "/search"), ("Pools", "/pools"), ("Sequences", "/sequences"),
           ("Skills", "/skills"), ("Analytics", "/analytics"), ("Careers", "/careers")]
    links = [A("💬 Chat with Ada", href="/", cls="primary")]
    links += [A(label, href=href) for label, href in nav]
    return Div(
        Aside(Div("FastATS", cls="brand"), Nav(*links),
              Small(user.get("organization_name", "")), cls="sidebar"),
        Main(*content, cls="content"), cls="shell")


def identity(session) -> dict | None:
    return session.get("identity")


def guard(session):
    if not identity(session):
        return RedirectResponse("/login", status_code=303)
    return None


@rt("/healthz")
def get():
    return JSONResponse({"ok": True, "database": db.dialect, "schema": db.schema})


@rt("/login")
def get(error: str = ""):
    google = A("Sign in with Google", href="/auth/google", cls="button secondary",
               style="display:block;text-align:center;margin-bottom:.8rem") if google_auth.enabled() else None
    return Div(Section(H1("Welcome to FastATS"), P("Recruiting operations with explainable AI.", cls="muted"),
        P(error, cls="flash danger") if error else None,
        google,
        Form(Label("Email", Input(name="email", type="email", value=settings.admin_email, required=True)),
             Label("Password", Input(name="password", type="password", required=True)),
             Button("Sign in"), method="post", action="/login"), cls="card"),
        style="max-width:440px;margin:10vh auto;padding:1rem")


@rt("/login")
def post(session, email: str, password: str):
    found = authenticate(db, email, password)
    if not found:
        return RedirectResponse("/login?error=" + quote("Invalid email or password"), status_code=303)
    session["identity"] = found
    return RedirectResponse("/", status_code=303)


@rt("/auth/google")
def get(session, request):
    if not google_auth.enabled():
        return RedirectResponse("/login?error=" + quote("Google sign-in is not configured"), status_code=303)
    state = google_auth.new_state()
    session["google_oauth_state"] = state
    return RedirectResponse(google_auth.authorize_url(request, state), status_code=303)


@rt("/auth/google/callback")
def get(session, request, code: str = "", state: str = "", error: str = ""):
    if error or not code or state != session.pop("google_oauth_state", None):
        return RedirectResponse("/login?error=" + quote("Google sign-in failed"), status_code=303)
    profile = google_auth.exchange(request, code)
    if not profile:
        return RedirectResponse("/login?error=" + quote("Google account not permitted"), status_code=303)
    found = google_identity(db, profile["email"], profile["name"])
    if not found:
        return RedirectResponse("/login?error=" + quote("No FastATS access for this account"), status_code=303)
    session["identity"] = found
    return RedirectResponse("/", status_code=303)


@rt("/logout")
def post(session):
    session.clear()
    return RedirectResponse("/login", status_code=303)


CHAT_JS = """
const TID = window.__TID__;
function el(h){const t=document.createElement('template');t.innerHTML=h.trim();return t.content.firstChild;}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
const stream=document.getElementById('stream'), canvas=document.getElementById('canvas');
function scr(){stream.scrollTop=stream.scrollHeight;}
function addMsg(role,text){const d=el('<div class="msg '+role+'"></div>');d.textContent=text;stream.appendChild(d);scr();return d;}
function renderArtifact(a){
  const c=el('<div class="acard"></div>'); let h='<h4>'+esc(a.title||a.kind)+'</h4>';
  if(a.kind==='candidates'){h+=(a.candidates||[]).map(x=>'<div><a href="/candidates/'+x.id+'">'+esc(x.name)+'</a> — '+esc(x.headline)+'</div>').join('')||'None';}
  else if(a.kind==='jobs'){h+=(a.jobs||[]).map(x=>'<div><a href="/jobs/'+x.id+'">'+esc(x.title)+'</a> ('+esc(x.status)+') — '+x.applications+'</div>').join('');}
  else if(a.kind==='pipeline'){h+=(a.stages||[]).map(x=>'<div>'+esc(x.stage)+': <b>'+x.count+'</b></div>').join('');}
  else if(a.kind==='candidate'){h+='<div><a href="/candidates/'+a.candidate_id+'">Open profile</a></div>'+(a.applications||[]).map(x=>'<div class="muted">'+esc(x.job)+' @ '+esc(x.stage)+'</div>').join('');}
  else if(a.kind==='draft'){h+='<textarea style="width:100%;min-height:150px">'+esc(a.body)+'</textarea><p class="muted">Review, then send from the candidate page.</p>';}
  else if(a.kind==='confirm'){var f='<form method="post" action="'+a.url+'">';const fl=a.fields||{};for(const k in fl){f+='<input type="hidden" name="'+k+'" value="'+esc(String(fl[k]))+'">';}f+='<button>'+esc(a.label||'Confirm')+'</button></form>';h+='<p>'+esc(a.text||'')+'</p>'+f;}
  else {h+='<p>'+esc(a.text||'')+'</p>';}
  c.innerHTML=h; const e=canvas.querySelector('.empty'); if(e)e.remove(); canvas.prepend(c);
}
async function send(text){
  text=(text||'').trim(); if(!text)return;
  addMsg('user',text); document.getElementById('box').value='';
  const bubble=addMsg('assistant',''); let acc='';
  let res; try{res=await fetch('/chat/'+TID+'/message',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'message='+encodeURIComponent(text)});}
  catch(e){bubble.textContent='Network error.';return;}
  const reader=res.body.getReader(), dec=new TextDecoder(); let buf='';
  while(true){const r=await reader.read(); if(r.done)break; buf+=dec.decode(r.value,{stream:true});
    let i; while((i=buf.indexOf('\\n\\n'))>=0){const raw=buf.slice(0,i); buf=buf.slice(i+2);
      if(!raw.startsWith('data:'))continue; let ev; try{ev=JSON.parse(raw.slice(5).trim());}catch(e){continue;}
      if(ev.event==='token'){acc+=ev.data; bubble.textContent=acc; scr();}
      else if(ev.event==='tool_start'){stream.insertBefore(el('<div class="msg tool">⚙ using '+esc(ev.data.name)+'…</div>'),bubble); scr();}
      else if(ev.event==='artifact'){renderArtifact(ev.data);}
      else if(ev.event==='error'){acc+='\\n['+ev.data.message+']'; bubble.textContent=acc;}
    }
  }
}
document.getElementById('composer').addEventListener('submit',e=>{e.preventDefault();send(document.getElementById('box').value);});
document.getElementById('box').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send(e.target.value);}});
document.querySelectorAll('.suggest button').forEach(b=>b.addEventListener('click',()=>send(b.textContent)));
"""

SUGGESTIONS = ["Who are my strongest backend candidates?", "Summarize the pipeline for each job",
               "Draft outreach to a promising candidate", "What should I focus on today?"]


def ensure_skills(organization_id: str, user_id: str | None) -> None:
    if not skills.skills(organization_id):
        skills.seed_builtins(organization_id, user_id)


def chat_page(session, thread: dict):
    me = identity(session)
    threads = chat.threads(me["organization_id"])
    left = Aside(Div("FastATS", cls="brand"),
        Form(Button("+ New chat", cls="secondary"), method="post", action="/chat/new"),
        Nav(*[A("💬 " + (t["title"] or "Conversation"),
                href=f"/chat/{t['id']}") for t in threads], cls="threadlist"),
        Small("Workspace", cls="muted", style="display:block;margin-top:1rem"),
        Nav(A("Dashboard", href="/dashboard"), A("Jobs", href="/jobs"), A("Candidates", href="/candidates"),
            A("Search", href="/search"), A("Pools", href="/pools"), A("Sequences", href="/sequences"),
            A("Skills", href="/skills"), A("Analytics", href="/analytics")),
        Small(me.get("organization_name", ""), style="margin-top:1rem;display:block"),
        cls="sidebar")

    bubbles = []
    for m in thread["messages"]:
        if m["role"] in ("user", "assistant"):
            bubbles.append(Div(m["content"], cls=f"msg {m['role']}"))
    if not bubbles:
        bubbles = [Div(H2("Hi, I'm Ada — your recruiting agent."),
                       P("Ask me to find candidates, summarize pipelines, draft outreach, or propose next steps. "
                         "I'll act through the whole app, and ask you to confirm anything that changes state.", cls="muted"),
                       Div(*[Button(s) for s in SUGGESTIONS], cls="suggest"), cls="empty")]

    center = Div(
        Div(H3(thread["title"] or "New conversation"),
            A("Skills", href="/skills", cls="button secondary"), cls="chathead"),
        Div(*bubbles, id="stream", cls="stream"),
        Form(Textarea(name="message", id="box", placeholder="Message Ada…  (Enter to send, Shift+Enter for newline)"),
             Button("Send"), id="composer", cls="composer"),
        cls="chatmain")
    canvas = Div(Div("Results and proposed actions appear here.", cls="empty"), id="canvas", cls="canvas")
    return Div(Div(left, center, canvas, cls="chatwrap"),
               Script(f"window.__TID__ = {json.dumps(thread['id'])};"),
               Script(CHAT_JS))


@rt("/")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    org = me["organization_id"]
    ensure_skills(org, me["user_id"])
    latest = chat.threads(org, limit=1)
    thread_id = latest[0]["id"] if latest else chat.create_thread(org, me["user_id"])
    return chat_page(session, chat.thread(org, thread_id))


@rt("/chat/{thread_id}")
def get(session, thread_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    thread = chat.thread(me["organization_id"], thread_id)
    if not thread:
        return Response("Not found", status_code=404)
    return chat_page(session, thread)


@rt("/chat/new")
def post(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    thread_id = chat.create_thread(me["organization_id"], me["user_id"])
    return RedirectResponse(f"/chat/{thread_id}", status_code=303)


@rt("/chat/{thread_id}/message")
async def post(session, thread_id: str, message: str = ""):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    org = me["organization_id"]
    thread = chat.thread(org, thread_id)
    if not thread:
        return Response("Not found", status_code=404)
    text = (message or "").strip()
    if not text:
        return Response("empty", status_code=400)
    history = list(thread["messages"])
    chat.add_message(org, thread_id, "user", text)
    chat.rename_from_first_message(org, thread_id, text)
    ctx = RecruiterContext(db, org, me["role"])

    async def gen():
        async for frame in stream_turn(ctx, text, history):
            yield frame
            try:
                payload = json.loads(frame[len("data: "):].strip())
                if payload.get("event") == "done":
                    data = payload["data"]
                    chat.add_message(org, thread_id, "assistant",
                                     data.get("text", ""), data.get("artifacts") or None)
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@rt("/skills")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    org = me["organization_id"]
    ensure_skills(org, me["user_id"])
    rows = skills.skills(org)
    cards = []
    for s in rows:
        toggle = "Disable" if s["enabled"] else "Enable"
        controls = [Form(Button(toggle, cls="secondary"), method="post", action=f"/skills/{s['id']}/toggle"),
                    A("Edit", href=f"/skills/{s['id']}", cls="button secondary")]
        if not s["is_builtin"]:
            controls.append(Form(Button("Delete", cls="secondary"), method="post", action=f"/skills/{s['id']}/delete"))
        cards.append(Article(H3(s["name"], Span(" · on" if s["enabled"] else " · off", cls="muted")),
            P(s["description"], cls="muted"),
            Small(f"Triggers: {s['triggers'] or '—'}", cls="muted"),
            Div(*controls, style="display:flex;gap:.5rem;margin-top:.6rem"), cls="card"))
    form = Article(H3("Create a skill"),
        Form(Label("Name", Input(name="name", required=True)),
             Label("Description", Input(name="description")),
             Label("Instructions (the agent follows these)", Textarea(name="instructions", required=True)),
             Label("Trigger keywords (comma-separated)", Input(name="triggers")),
             Button("Add skill"), method="post", action="/skills"), cls="card")
    return shell(session, "skills", H1("Editable skills"),
        P("Skills are playbooks that shape how Ada works. Enabled skills are added to her instructions; "
          "triggers surface a skill when your message matches. Edit them freely — no code needed.", cls="muted"),
        form, Div(*cards, cls="grid"))


@rt("/skills")
def post(session, name: str, instructions: str, description: str = "", triggers: str = ""):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    skills.create_skill(me["organization_id"], name=name, description=description,
                        instructions=instructions, triggers=triggers, created_by=me["user_id"])
    return RedirectResponse("/skills", status_code=303)


@rt("/skills/{skill_id}")
def get(session, skill_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    s = skills.skill(me["organization_id"], skill_id)
    if not s:
        return Response("Not found", status_code=404)
    return shell(session, "skills", H1(f"Edit skill · {s['name']}"),
        Article(Form(Label("Name", Input(name="name", value=s["name"], required=True)),
            Label("Description", Input(name="description", value=s["description"])),
            Label("Instructions", Textarea(s["instructions"], name="instructions", required=True)),
            Label("Trigger keywords", Input(name="triggers", value=s["triggers"] or "")),
            Button("Save"), method="post", action=f"/skills/{skill_id}"), cls="card"),
        P(A("← Back to skills", href="/skills"), cls="muted"))


@rt("/skills/{skill_id}")
def post(session, skill_id: str, name: str, instructions: str, description: str = "", triggers: str = ""):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    skills.update_skill(me["organization_id"], skill_id, name=name, description=description,
                       instructions=instructions, triggers=triggers)
    return RedirectResponse("/skills", status_code=303)


@rt("/skills/{skill_id}/toggle")
def post(session, skill_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    skills.toggle(me["organization_id"], skill_id)
    return RedirectResponse("/skills", status_code=303)


@rt("/skills/{skill_id}/delete")
def post(session, skill_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    skills.delete_skill(me["organization_id"], skill_id)
    return RedirectResponse("/skills", status_code=303)


@rt("/dashboard")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    jobs = ats.jobs(me["organization_id"])
    candidates = ats.candidates(me["organization_id"])
    active = sum(int(job["applications"] or 0) for job in jobs)
    return shell(session, "dashboard",
        Header(H1("Recruiting overview"), P(f"{me['name']} · {me['role']}", cls="muted"), cls="top"),
        Div(Article(Small("Open roles"), Div(str(sum(j["status"] == "Published" for j in jobs)), cls="metric"), cls="card"),
            Article(Small("Candidates"), Div(str(len(candidates)), cls="metric"), cls="card"),
            Article(Small("Applications"), Div(str(active), cls="metric"), cls="card"), cls="grid"),
        H2("Recent roles"), Div(*[Article(H3(A(j["title"], href=f"/jobs/{j['id']}")),
            P(j["location"], cls="muted"), Span(f"{j['applications']} applications", cls="pill"), cls="card") for j in jobs], cls="grid"))


@rt("/jobs")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    jobs = ats.jobs(me["organization_id"])
    return shell(session, "jobs", Header(H1("Jobs"), A("Create job", href="/jobs/new", cls="button"), cls="top"),
        Div(*[Article(H3(A(job["title"], href=f"/jobs/{job['id']}")), P(job["location"], cls="muted"),
             Span(job["status"], cls="pill"), P(f"{job['applications']} applications"), cls="card") for job in jobs], cls="grid"))


@rt("/jobs/new")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    return shell(session, "jobs", H1("Create job"), Article(Form(
        Label("Title", Input(name="title", required=True)), Label("Location", Input(name="location")),
        Label("Employment type", Select(Option("Permanent"), Option("Contract"), Option("Intern"), name="employment_type")),
        Label("Description", Textarea(name="description", required=True)),
        Label("Requirements", Textarea(name="requirements", required=True)), Button("Create draft"),
        method="post", action="/jobs"), cls="card"))


@rt("/jobs")
def post(session, title: str, description: str, requirements: str, location: str = "",
         employment_type: str = "Permanent"):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    job_id = ats.create_job(me["organization_id"], title=title, description=description,
        requirements=requirements, location=location, employment_type=employment_type, created_by=me["user_id"])
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@rt("/jobs/{job_id}")
def get(session, job_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    job = ats.job(me["organization_id"], job_id)
    if not job:
        return Response("Not found", status_code=404)
    stages = ats.pipeline(me["organization_id"], job_id)
    columns = []
    for stage in stages:
        cards = []
        for application in stage["applications"]:
            options = [Option(target["name"], value=target["id"], selected=target["id"] == stage["id"]) for target in stages]
            cards.append(Div(H3(A(f"{application['first_name']} {application['last_name']}",
                                  href=f"/candidates/{application['candidate_id']}")),
                P(application["headline"] or application["email"], cls="muted"),
                Form(Select(*options, name="stage_id"), Button("Move", cls="secondary"),
                     method="post", action=f"/applications/{application['id']}/stage"), cls="candidate"))
        columns.append(Section(H3(Span(stage["name"]), Span(str(len(cards)), cls="pill")), *cards, cls="column"))
    publish = Form(Button("Publish job"), method="post", action=f"/jobs/{job_id}/publish") if job["status"] == "Draft" else Span(job["status"], cls="pill")
    return shell(session, "jobs", Header(Div(H1(job["title"]), P(job["location"], cls="muted")), publish, cls="top"),
                 Div(*columns, cls="pipeline"))


@rt("/jobs/{job_id}/publish")
def post(session, job_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    ats.publish_job(me["organization_id"], job_id, me["user_id"])
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@rt("/applications/{application_id}/stage")
def post(session, application_id: str, stage_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    application = db.one("SELECT job_id FROM applications WHERE id=? AND organization_id=?",
                         (application_id, me["organization_id"]))
    if not application:
        return Response("Not found", status_code=404)
    ats.move_application(me["organization_id"], application_id, stage_id, me["user_id"], me["role"])
    return RedirectResponse(f"/jobs/{application['job_id']}", status_code=303)


@rt("/candidates")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    rows = ats.candidates(me["organization_id"])
    return shell(session, "candidates", H1("Candidates"), Div(*[
        Article(H3(A(f"{c['first_name']} {c['last_name']}", href=f"/candidates/{c['id']}")),
                P(c["headline"] or c["email"]), Span(c["source"], cls="pill"), cls="card") for c in rows], cls="grid"))


@rt("/candidates/{candidate_id}")
def get(session, candidate_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    candidate = ats.candidate(me["organization_id"], candidate_id)
    if not candidate:
        return Response("Not found", status_code=404)
    org = me["organization_id"]
    applications = []
    for application in candidate["applications"]:
        screening = None
        if application.get("screening_status"):
            screening = Div(
                H3(f"AI screening · {application['screening_score'] or '—'}/100"),
                Span(application.get("screening_recommendation") or application["screening_status"], cls="pill"),
                P(application.get("screening_explanation") or application["screening_status"]),
                Small("Assistive score only — a recruiter controls every stage decision.", cls="muted"))
        cards = interviews.scorecards_for(org, application["id"])
        scorecard_view = [Div(Span(f"{c['interviewer_name'] or 'Interviewer'} · {c['recommendation'] or ''}", cls="pill"),
                              P(f"Overall {c['overall'] or '—'} — {c['summary'] or ''}", cls="muted")) for c in cards]
        booked = interviews.interviews_for(org, application["id"])
        interview_view = [P(f"{iv['title']} · {iv['status']} · feedback {iv['feedback_status']}", cls="muted") for iv in booked]
        applications.append(Article(
            H3(application["job_title"]), Span(application["stage_name"], cls="pill"), screening,
            *interview_view, *scorecard_view,
            Form(Input(name="title", placeholder="Interview title", required=True),
                 Button("Schedule interview", cls="secondary"), method="post",
                 action=f"/applications/{application['id']}/interviews"),
            Form(Input(name="summary", placeholder="Scorecard summary"),
                 Input(name="overall", type="number", step="0.5", placeholder="Overall (0-5)"),
                 Input(name="recommendation", placeholder="Recommendation"),
                 Button("Submit scorecard", cls="secondary"), method="post",
                 action=f"/applications/{application['id']}/scorecards"),
            Form(Button("Queue AI screening", cls="secondary"), method="post",
                 action=f"/applications/{application['id']}/screen"), cls="card"))
    tag_pills = [Span(t["name"], cls="pill") for t in ats.tags_for(org, "candidate", candidate_id)]
    notes = ats.notes(org, "candidate", candidate_id)
    note_items = [Li(P(n["body"]), Small(f"{n['author_name'] or 'System'} · {n['created_at']}", cls="muted")) for n in notes]
    messages = crm.messages_for(org, candidate_id)
    message_items = [Li(f"{m['subject'] or '(no subject)'} · {m['status']} · {m['created_at']}") for m in messages]
    events = [Li(f"{event['event_type']} · {event['created_at']}") for event in candidate["activity"]]
    left = Section(
        H2("Applications"), *applications,
        H2("Tags"), Div(*tag_pills or [Small("No tags", cls="muted")]),
        Form(Input(name="name", placeholder="Add tag", required=True), Button("Tag", cls="secondary"),
             method="post", action=f"/candidates/{candidate_id}/tags"),
        H2("Notes"),
        Form(Textarea(name="body", placeholder="Add a private note", required=True), Button("Add note"),
             method="post", action=f"/candidates/{candidate_id}/notes"),
        Ul(*note_items or [Li(Small("No notes yet", cls="muted"))], cls="activity"))
    right = Section(H2("Messages"), Ul(*message_items or [Li(Small("No messages", cls="muted"))], cls="activity"),
                    H2("Activity"), Ul(*events, cls="activity"))
    return shell(session, "candidates", Header(Div(H1(f"{candidate['first_name']} {candidate['last_name']}"),
        P(candidate["headline"] or candidate["email"], cls="muted")), Span(candidate["source"], cls="pill"), cls="top"),
        Div(left, right, cls="split"))


@rt("/applications/{application_id}/screen")
def post(session, application_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    application = db.one("SELECT candidate_id FROM applications WHERE id=? AND organization_id=?",
                         (application_id, me["organization_id"]))
    if not application:
        return Response("Not found", status_code=404)
    ats.enqueue_screening(me["organization_id"], application_id)
    ats.log(me["organization_id"], "application", application_id, "screening.queued", me["user_id"], {})
    return RedirectResponse(f"/candidates/{application['candidate_id']}", status_code=303)


@rt("/careers")
def get():
    jobs = ats.public_jobs()
    return Main(Header(H1("Open roles"), A("Recruiter sign in", href="/login", cls="button secondary")),
        P("Find the work where you can do your best.", cls="muted"),
        *[Article(H2(A(job["title"], href=f"/careers/{job['organization_slug']}/{job['slug']}")),
                  P(f"{job['organization_name']} · {job['location']}"), cls="card") for job in jobs], cls="career")


@rt("/careers/{organization_slug}/{job_slug}")
def get(organization_slug: str, job_slug: str, error: str = "", sent: str = ""):
    job = ats.public_job(organization_slug, job_slug)
    if not job:
        return Response("Job not found", status_code=404)
    form = Form(Label("First name", Input(name="first_name", required=True)),
        Label("Last name", Input(name="last_name", required=True)),
        Label("Email", Input(name="email", type="email", required=True)),
        Label("Phone", Input(name="phone")), Label("Location", Input(name="location")),
        Label("Resume", Input(name="resume", type="file", accept=".pdf,.docx,.txt,.md", required=True)),
        Label(Span("I consent to the use of my information for this application"),
              Input(name="consent", value="yes", type="checkbox", required=True)),
        Button("Submit application"), method="post", enctype="multipart/form-data")
    return Main(A("← All roles", href="/careers"), H1(job["title"]),
        P(f"{job['organization_name']} · {job['location']} · {job['employment_type']}", cls="muted"),
        P(sent, cls="flash") if sent else None, P(error, cls="flash danger") if error else None,
        Article(H2("About the role"), P(job["description"]), H2("What we're looking for"),
                P(job["requirements"]), cls="card"), Article(H2("Apply"), form, cls="card"), cls="career")


@rt("/careers/{organization_slug}/{job_slug}")
async def post(request, organization_slug: str, job_slug: str):
    form = await request.form()
    try:
        upload = form.get("resume")
        if not upload or not getattr(upload, "filename", ""):
            raise ValueError("A resume is required")
        data = await upload.read()
        text = extract_text(upload.filename, data)
        result = ats.public_apply(organization_slug, job_slug, {"first_name": str(form.get("first_name", "")),
            "last_name": str(form.get("last_name", "")), "email": str(form.get("email", "")),
            "phone": str(form.get("phone", "")), "location": str(form.get("location", "")),
            "consent": str(form.get("consent", ""))})
        key = storage.put(result["organization_id"], upload.filename, data)
        document_id = ats.add_document(result["organization_id"], result["candidate_id"],
            result["application_id"], file_name=upload.filename,
            content_type=getattr(upload, "content_type", "application/octet-stream"),
            object_key=key, extracted_text=text)
        ats.enqueue_screening(result["organization_id"], result["application_id"], document_id)
        ats.enqueue_embedding(result["organization_id"], "candidate", result["candidate_id"],
                              f"{result['job']['title']} {text[:8000]}")
    except ValueError as exc:
        return RedirectResponse(f"/careers/{organization_slug}/{job_slug}?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/careers/{organization_slug}/{job_slug}?sent={quote('Application received. Thank you.')}", status_code=303)


@rt("/candidates/{candidate_id}/notes")
def post(session, candidate_id: str, body: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    ats.add_note(me["organization_id"], "candidate", candidate_id, body, me["user_id"])
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@rt("/candidates/{candidate_id}/tags")
def post(session, candidate_id: str, name: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    ats.tag_entity(me["organization_id"], "candidate", candidate_id, name)
    return RedirectResponse(f"/candidates/{candidate_id}", status_code=303)


@rt("/applications/{application_id}/interviews")
def post(session, application_id: str, title: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    application = db.one("SELECT candidate_id FROM applications WHERE id=? AND organization_id=?",
                         (application_id, me["organization_id"]))
    if not application:
        return Response("Not found", status_code=404)
    interviews.schedule(me["organization_id"], application_id=application_id, title=title,
                        interviewer_ids=[me["user_id"]], created_by=me["user_id"])
    return RedirectResponse(f"/candidates/{application['candidate_id']}", status_code=303)


@rt("/applications/{application_id}/scorecards")
def post(session, application_id: str, summary: str = "", overall: str = "", recommendation: str = ""):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    application = db.one("SELECT candidate_id FROM applications WHERE id=? AND organization_id=?",
                         (application_id, me["organization_id"]))
    if not application:
        return Response("Not found", status_code=404)
    try:
        score = float(overall) if overall else None
    except ValueError:
        score = None
    interviews.submit_scorecard(me["organization_id"], application_id=application_id,
        interviewer_user_id=me["user_id"], answers=[], overall=score,
        recommendation=recommendation, summary=summary)
    return RedirectResponse(f"/candidates/{application['candidate_id']}", status_code=303)


@rt("/search")
def get(session, q: str = ""):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    results = search_candidates(db, me["organization_id"], q) if q else []
    cards = [Article(H3(A(f"{c['first_name']} {c['last_name']}", href=f"/candidates/{c['id']}")),
                     P(c["headline"] or c["email"], cls="muted"),
                     Span(f"score {c.get('score', 0)}", cls="pill"), cls="card") for c in results]
    note = Small("Semantic search over resumes and profiles. Falls back to keyword match "
                 "when embeddings are unavailable.", cls="muted")
    return shell(session, "search", H1("Search candidates"),
        Form(Input(name="q", value=q, placeholder="e.g. backend engineer with Postgres"),
             Button("Search"), method="get", action="/search"), note,
        Div(*cards or [P("No results.", cls="muted")], cls="grid"))


@rt("/pools")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    pools = crm.pools(me["organization_id"])
    return shell(session, "pools", H1("Talent pools"),
        Article(Form(Label("Name", Input(name="name", required=True)),
             Label("Description", Input(name="description")),
             Button("Create pool"), method="post", action="/pools"), cls="card"),
        Div(*[Article(H3(A(p["name"], href=f"/pools/{p['id']}")),
                      P(p["description"] or "", cls="muted"),
                      Span(f"{p['members']} candidates", cls="pill"), cls="card")
              for p in pools], cls="grid"))


@rt("/pools")
def post(session, name: str, description: str = ""):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    crm.create_pool(me["organization_id"], name=name, description=description, created_by=me["user_id"])
    return RedirectResponse("/pools", status_code=303)


@rt("/pools/{pool_id}")
def get(session, pool_id: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    members = crm.pool_members(me["organization_id"], pool_id)
    return shell(session, "pools", H1("Pool"),
        Div(*[Article(H3(A(f"{c['first_name']} {c['last_name']}", href=f"/candidates/{c['id']}")),
                      P(c["headline"] or c["email"], cls="muted"), cls="card")
              for c in members] or [P("No candidates in this pool.", cls="muted")], cls="grid"))


@rt("/sequences")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    sequences = crm.sequences(me["organization_id"])
    return shell(session, "sequences", H1("Email sequences"),
        Article(Form(Label("Name", Input(name="name", required=True)),
             Label("Step 1 subject", Input(name="subject", required=True)),
             Label("Step 1 body", Textarea(name="body", required=True)),
             Button("Create sequence"), method="post", action="/sequences"), cls="card"),
        Div(*[Article(H3(s["name"]), Span(f"{s['step_count']} steps", cls="pill"),
                      P(f"{s['enrolled']} enrolled", cls="muted"), cls="card")
              for s in sequences], cls="grid"))


@rt("/sequences")
def post(session, name: str, subject: str, body: str):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    crm.create_sequence(me["organization_id"], name=name, created_by=me["user_id"],
                        steps=[{"subject": subject, "body": body, "delay_hours": 0}])
    return RedirectResponse("/sequences", status_code=303)


@rt("/analytics")
def get(session):
    denied = guard(session)
    if denied:
        return denied
    me = identity(session)
    org = me["organization_id"]
    overview = analytics.overview(org)
    sources = analytics.source_effectiveness(org)
    tis = analytics.time_in_stage(org)
    jobs = ats.jobs(org)
    funnels = []
    for job in jobs[:5]:
        rows = analytics.funnel(org, job["id"])
        bars = [Div(Span(r["name"], cls="muted"), Span(str(r["count"]), cls="pill")) for r in rows]
        funnels.append(Article(H3(job["title"]), *bars, cls="card"))
    source_rows = [Tr(Td(s["source"]), Td(str(s["total"])), Td(str(s["hired"] or 0))) for s in sources]
    tis_rows = [Tr(Td(stage), Td(f"{days} days")) for stage, days in tis.items()]
    return shell(session, "analytics", H1("Analytics"),
        Div(Article(Small("Open roles"), Div(str(overview["open_roles"]), cls="metric"), cls="card"),
            Article(Small("Applications"), Div(str(overview["applications"]), cls="metric"), cls="card"),
            Article(Small("Hired"), Div(str(overview["hired"]), cls="metric"), cls="card"), cls="grid"),
        H2("Pipeline funnels"), Div(*funnels, cls="grid"),
        H2("Source effectiveness"),
        Table(Thead(Tr(Th("Source"), Th("Applications"), Th("Hired"))), Tbody(*source_rows), cls="card"),
        H2("Average time in stage"),
        Table(Thead(Tr(Th("Stage"), Th("Avg days"))), Tbody(*tis_rows), cls="card"))


@rt("/assistant")
def get(session):
    # The assistant is now the primary chat surface at /.
    return RedirectResponse("/", status_code=303)


@rt("/tools/content")
def get(session, kind: str = "jd", title: str = "", notes: str = ""):
    denied = guard(session)
    if denied:
        return denied
    output = None
    if title:
        output = _generate_content(kind, title, notes)
    kinds = [("jd", "Job description"), ("questions", "Interview questions")]
    return shell(session, "assistant", H1("AI content helpers"),
        Form(Select(*[Option(label, value=value, selected=value == kind) for value, label in kinds], name="kind"),
             Label("Role title", Input(name="title", value=title, required=True)),
             Label("Notes", Textarea(name="notes", value=notes or "")),
             Button("Generate"), method="get", action="/tools/content"),
        Article(H3("Draft"), Pre(output), cls="card") if output is not None else None)


def _generate_content(kind: str, title: str, notes: str) -> str:
    if not settings.xai_api_key:
        return "Set XAI_API_KEY in .env to generate content."
    try:
        from agents.models import build_chat_model
        model = build_chat_model()
        if kind == "questions":
            return content.generate_interview_questions(model, role_title=title, focus=notes)
        return content.generate_job_description(model, title=title, notes=notes)
    except Exception as exc:
        return f"Generation error: {exc}"


if __name__ == "__main__":
    uvicorn.run("web_app:app", host="0.0.0.0", port=settings.port, reload=False)

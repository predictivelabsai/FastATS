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
from starlette.responses import JSONResponse, RedirectResponse, Response

from agents import content
from analytics import AnalyticsService
from ats import ATSService
from auth import authenticate, google_identity
from web import google_auth
from config import settings
from crm import CRMService
from database import get_database
from documents import extract_text
from interviews import InterviewService
from seed import build
from semantic import search_candidates
from storage import get_storage

CSS = """
:root{--ink:#1e1d2b;--muted:#6d6a7d;--line:#e5e3ec;--panel:#fff;--bg:#f7f7fb;--brand:#5145cd;--soft:#eeecff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,sans-serif}
a{color:inherit;text-decoration:none}button,.button{border:0;border-radius:8px;background:var(--brand);color:#fff;padding:.65rem .9rem;font-weight:650;cursor:pointer}
button.secondary,.button.secondary{background:#fff;color:var(--ink);border:1px solid var(--line)}input,textarea,select{width:100%;padding:.7rem;border:1px solid #d9d6e2;border-radius:8px;background:#fff;font:inherit}textarea{min-height:120px}label{display:grid;gap:.35rem;font-weight:600;margin:.7rem 0}.shell{display:grid;grid-template-columns:220px 1fr;min-height:100vh}.sidebar{background:#19182a;color:#e9e8f5;padding:1.25rem}.brand{font-size:1.25rem;font-weight:800;margin-bottom:1.5rem}.sidebar a{display:block;padding:.65rem .75rem;border-radius:8px;color:#c9c6dd}.sidebar a:hover{background:#292741;color:#fff}.content{padding:2rem;max-width:1500px;width:100%;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem}.top h1{margin:0}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:1rem;box-shadow:0 1px 2px #1111}.metric{font-size:2rem;font-weight:800}.pipeline{display:grid;grid-template-columns:repeat(6,minmax(220px,1fr));gap:.8rem;overflow-x:auto;padding-bottom:1rem}.column{background:#eeedf4;border-radius:12px;padding:.7rem;min-height:240px}.column h3{display:flex;justify-content:space-between;margin:.3rem}.candidate{background:#fff;border:1px solid var(--line);border-radius:9px;padding:.75rem;margin:.65rem 0}.candidate form{margin-top:.65rem}.pill{display:inline-block;border-radius:999px;background:var(--soft);color:#4338a8;padding:.2rem .55rem;font-size:.8rem}.career{max-width:850px;margin:0 auto;padding:2rem}.career header{display:flex;justify-content:space-between;align-items:center}.split{display:grid;grid-template-columns:2fr 1fr;gap:1rem}.flash{padding:.8rem;border-radius:8px;background:#e9f8ef;color:#175d34}.danger{background:#fff0f0;color:#9b2424}.activity{border-left:2px solid var(--line);padding-left:1rem}.activity li{margin:.6rem 0}@media(max-width:850px){.shell{grid-template-columns:1fr}.sidebar{display:none}.grid,.split{grid-template-columns:1fr}.content{padding:1rem}}
"""

db = get_database()
db.migrate()
build(db)
ats = ATSService(db)
crm = CRMService(db)
interviews = InterviewService(db)
analytics = AnalyticsService(db)
storage = get_storage()
app, rt = fast_app(live=False, pico=False, secret_key=settings.secret,
                   hdrs=[Title("FastATS"), Meta(name="viewport", content="width=device-width,initial-scale=1"), Style(CSS)])


def shell(session, active: str, *content):
    user = session.get("identity", {})
    nav = [("Dashboard", "/"), ("Jobs", "/jobs"), ("Candidates", "/candidates"),
           ("Search", "/search"), ("Pools", "/pools"), ("Sequences", "/sequences"),
           ("Assistant", "/assistant"), ("Analytics", "/analytics"), ("Careers", "/careers")]
    return Div(
        Aside(Div("FastATS", cls="brand"), Nav(*[A(label, href=href) for label, href in nav]),
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


@rt("/")
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
def get(session, q: str = ""):
    denied = guard(session)
    if denied:
        return denied
    answer = None
    if q:
        answer = _assistant_answer(session, q)
    return shell(session, "assistant", H1("Recruiting assistant"),
        P("Ask about candidates, pipelines, or draft outreach. The assistant is read-only — "
          "it never moves stages or sends email.", cls="muted"),
        Form(Textarea(name="q", placeholder="e.g. Who are my strongest backend candidates?", value=q or ""),
             Button("Ask"), method="get", action="/assistant"),
        Article(H3("Answer"), Pre(answer), cls="card") if answer is not None else None)


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


def _assistant_answer(session, question: str) -> str:
    me = identity(session)
    if not settings.xai_api_key:
        return ("The assistant needs XAI_API_KEY configured to run. Add it to .env and restart. "
                "Search and analytics work without it.")
    try:
        from agents.assistant import AssistantContext, build_assistant_graph
        from agents.models import build_chat_model
        graph = build_assistant_graph(build_chat_model(), AssistantContext(db, me["organization_id"]))
        result = graph.invoke({"messages": [{"role": "user", "content": question}]})
        messages = result.get("messages", [])
        return getattr(messages[-1], "content", str(messages[-1])) if messages else "(no answer)"
    except Exception as exc:
        return f"Assistant error: {exc}"


if __name__ == "__main__":
    uvicorn.run("web_app:app", host="0.0.0.0", port=settings.port, reload=False)

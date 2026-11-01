# 提供审查服务的 HTTP 接口、GitHub Webhook 与管理台静态页面；所有路由在文件末尾集中注册。
import hashlib
import json
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any, ClassVar, cast

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.config import Settings
from ..core.modes import public_taxonomy, resolve_mode
from ..integrations.github import verify_signature
from ..integrations.metrics import metrics
from ..review.report import to_markdown
from ..services.review_service import ReviewService
from .auth import Principal

SERVER_VERSION = "EvoAgent/0.3"
WEB_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web"))
# 管理台只公开固定的静态资源，避免通过路径参数读取 web/ 之外的文件。
STATIC_ASSETS = {"app.css": "app.css", "login.css": "login.css", "app.js": "app.js"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Server": SERVER_VERSION,
}

TaskId = Annotated[str, Path(pattern=r"^[0-9a-f-]+$")]
SkillName = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$")]
ArtifactName = Annotated[str, Path(pattern=r"^[a-z0-9_-]+$")]
Version = Annotated[int, Path(ge=0)]


# ---------------------------------------------------------------------------
# 请求体：只声明接口真正读取的字段；未知字段忽略以兼容现有客户端。
# ---------------------------------------------------------------------------


class RequestBody(BaseModel):
    """所有请求体的基类；忽略额外字段，保持与旧版宽松 JSON 解析一致。"""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")


class LoginBody(RequestBody):
    username: str = ""
    password: str = ""
    tenant_id: str = ""


class ReviewBody(RequestBody):
    """创建审查任务；diff 大小与仓库名的业务校验由 ReviewService 负责。"""

    repository: str = ""
    diff: str = ""
    pull_request: StrictInt | None = None
    mode: str = ""
    repository_root: str = ""
    enabled_agents: list[str] | None = None
    enabled_skills: list[str] | None = None


class FixBody(RequestBody):
    installation_id: StrictInt | None = None


class FeedbackBody(RequestBody):
    category: str = ""
    finding: Any = None
    note: str = ""


class DeadLetterReplayBody(RequestBody):
    message_id: str = ""


class EvaluationCaseBody(RequestBody):
    name: str = ""
    diff: str = ""
    expected_findings: list[Any] = Field(default_factory=list)
    split: str = "validation"


class EvolutionAutoBody(RequestBody):
    skill_name: str = "llm-review"


class EvolutionProposeBody(RequestBody):
    skill_name: str = ""
    prompt: str = ""
    regression_score: float | None = None


class SkillEvolutionAutoBody(RequestBody):
    skill_name: str = "evolved-review"


class SkillEvolutionProposeBody(RequestBody):
    """直接提交 artifact，或以 skill_md + supporting_files 的简写形式提交。"""

    skill_name: str = ""
    artifact: Any = None
    skill_md: str | None = None
    supporting_files: dict[str, Any] | None = None

    def resolved_artifact(self) -> Any:
        if self.artifact is None and self.skill_md is not None:
            return {
                "name": self.skill_name,
                "skill_md": self.skill_md,
                "supporting_files": self.supporting_files or {},
            }
        return self.artifact


# ---------------------------------------------------------------------------
# 响应与错误：统一使用 {"error": ...} 结构，前端只需读取一个字段。
# ---------------------------------------------------------------------------


class Unauthorized(Exception):
    """身份认证失败（缺少或无效的 Token），映射为 401 以触发前端登录层。"""


class EvoJSONResponse(JSONResponse):
    """保留中文原文输出，并把数据库返回的非常规类型（如 datetime）转为字符串。"""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str).encode("utf-8")


def error(status: int, message: str, **extra: Any) -> EvoJSONResponse:
    return EvoJSONResponse({"error": message, **extra}, status_code=status)


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if any(item.get("type") == "json_invalid" for item in errors):
        return "request body must be valid UTF-8 JSON"
    if any(item.get("type") == "missing" and tuple(item.get("loc", ())) == ("body",) for item in errors):
        return "request body is required"
    parts = []
    for item in errors:
        location = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
        parts.append("%s: %s" % (location, item.get("msg", "invalid value")) if location else str(item.get("msg")))
    return "; ".join(parts) or "invalid request"


# 应用生命周期负责创建与释放 ReviewService；各路由只通过 get_service() 访问业务层。
def create_app(settings: Settings, service: ReviewService | None = None) -> FastAPI:
    """构造 EvoAgent HTTP 应用。

    业务服务在 lifespan 中创建并在关闭时释放队列连接；测试可以注入现成的 service。
    处理函数均为同步函数，由 FastAPI 在线程池中执行，避免阻塞事件循环。
    认证与权限通过 authorize() 依赖统一处理，错误通过 exception_handler 统一映射状态码。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        owned = service is None
        current = service or ReviewService(settings)
        app.state.service = current
        print("EvoAgent dashboard: http://%s:%d" % (settings.host, settings.port))
        print("Persistence: %s | Queue: %s | Orchestrator: %s" % (
            "postgresql" if settings.database_url else "sqlite",
            current.queue.backend, current.reviewer.name,
        ))
        try:
            yield
        finally:
            if owned:
                current.queue.close()

    app = FastAPI(
        title="EvoAgent PR Reviewer",
        version="0.3.0",
        lifespan=lifespan,
        default_response_class=EvoJSONResponse,
    )
    body_limit = settings.max_diff_bytes + 256 * 1024

    def get_service() -> ReviewService:
        """生命周期已在 app.state 写入服务实例；在框架的动态 State 边界恢复类型。"""
        return cast(ReviewService, app.state.service)

    def llm_summary() -> dict[str, Any]:
        config = get_service().llm_config
        return {
            "enabled": bool(config),
            "provider": config.get("provider", "local"),
            "model": config.get("model", ""),
        }

    def run_mode() -> dict[str, Any]:
        return resolve_mode(None, bool(get_service().llm_config)).to_dict()

    def audit(principal: Principal, action: str, target: str, detail: dict[str, Any] | None = None) -> None:
        if detail is None:
            get_service().store.audit(principal.tenant_id, principal.username, action, target)
        else:
            get_service().store.audit(principal.tenant_id, principal.username, action, target, detail)

    # ----------------------------- 依赖 -----------------------------

    def authorize(permission: str) -> Callable[..., Principal]:
        """生成指定权限的认证依赖：Token 无效返回 401，权限不足返回 403。"""

        def dependency(authorization: Annotated[str, Header()] = "") -> Principal:
            if not settings.auth_required:
                return Principal("local", "local-development", settings.default_tenant_id, "admin")
            auth = get_service().auth
            try:
                principal = auth.authenticate(authorization)
            except PermissionError as exc:
                raise Unauthorized(str(exc)) from exc
            auth.require(principal, (permission,))
            return principal

        return dependency

    Reader = Annotated[Principal, Depends(authorize("read"))]
    Reviewer = Annotated[Principal, Depends(authorize("review"))]
    Fixer = Annotated[Principal, Depends(authorize("fix"))]
    Manager = Annotated[Principal, Depends(authorize("manage"))]
    Auditor = Annotated[Principal, Depends(authorize("audit"))]

    async def raw_body(request: Request) -> bytes:
        """Webhook 签名必须基于原始字节计算，因此单独读取未经解析的请求体。"""
        return await request.body()

    # ----------------------------- 中间件与异常 -----------------------------

    async def guard(request: Request, call_next: Callable[[Request], Any]) -> Response:
        """统一限制请求体大小并为所有响应附加安全响应头。"""
        if request.method in {"POST", "PUT", "PATCH"}:
            length = request.headers.get("content-length")
            if length is None and request.headers.get("transfer-encoding"):
                response: Response = error(411, "Content-Length is required")
            else:
                try:
                    too_large = int(length or "0") > body_limit
                except ValueError:
                    too_large = None
                if too_large is None:
                    response = error(400, "invalid Content-Length")
                elif too_large:
                    response = error(413, "request body is too large")
                else:
                    response = await call_next(request)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    async def unauthorized(_: Request, exc: Exception) -> Response:
        return error(401, str(exc))

    async def forbidden(_: Request, exc: Exception) -> Response:
        return error(403, str(exc) or "permission denied")

    async def bad_request(_: Request, exc: Exception) -> Response:
        return error(400, str(exc))

    async def invalid_request(_: Request, exc: Exception) -> Response:
        validation = cast(RequestValidationError, exc)
        # 路径参数格式不符（如非法任务 ID）等同于资源不存在，与旧版正则路由行为一致。
        if all(tuple(item.get("loc", ()))[:1] == ("path",) for item in validation.errors()):
            return error(404, "not found")
        return error(400, _validation_message(validation))

    async def http_error(_: Request, exc: Exception) -> Response:
        http_exc = cast(StarletteHTTPException, exc)
        detail = http_exc.detail if isinstance(http_exc.detail, str) else "request failed"
        return error(http_exc.status_code, detail.lower() if detail == "Not Found" else detail)

    async def server_error(_: Request, exc: Exception) -> Response:
        metrics.inc("http_errors_total")
        return error(500, "operation failed", detail=str(exc))

    # ----------------------------- 静态页面 -----------------------------

    def index() -> FileResponse:
        return FileResponse(os.path.join(WEB_ROOT, "index.html"))

    def asset(name: str) -> FileResponse:
        filename = STATIC_ASSETS.get(name)
        if filename is None:
            raise HTTPException(404, "not found")
        return FileResponse(os.path.join(WEB_ROOT, filename))

    # ----------------------------- 系统与认证 -----------------------------

    def health() -> dict[str, Any]:
        current = get_service()
        return {
            "status": "ok",
            "reviewer": current.reviewer.name,
            "runtime": current.harness.name,
            "queue": current.queue.backend,
            "llm_provider": current.llm_config.get("provider", "local"),
            "llm_model": current.llm_config.get("model", ""),
            "run_mode": run_mode(),
            "taxonomy": public_taxonomy(),
        }

    def prometheus(_: Reader) -> Response:
        return Response(metrics.prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")

    def login(body: LoginBody) -> Any:
        if not settings.auth_required:
            return error(409, "authentication is disabled")
        try:
            return get_service().auth.login(body.username, body.password, body.tenant_id)
        except PermissionError as exc:
            raise Unauthorized(str(exc)) from exc

    # ----------------------------- 管理台数据 -----------------------------

    def dashboard(principal: Reader) -> dict[str, Any]:
        current = get_service()
        return {
            "stats": current.store.dashboard_stats(principal.tenant_id),
            "tasks": current.store.list_tasks(10, principal.tenant_id),
            "queue": current.queue.backend,
            "orchestrator": current.reviewer.name,
            "llm": llm_summary(),
            "run_mode": run_mode(),
            "taxonomy": public_taxonomy(),
        }

    def list_tasks(principal: Reader, limit: Annotated[int, Query()] = 50) -> dict[str, Any]:
        return {"tasks": get_service().store.list_tasks(limit, principal.tenant_id)}

    def list_skills(principal: Reader) -> dict[str, Any]:
        return {"skills": get_service().list_skills(principal.tenant_id), "llm": llm_summary()}

    def list_failures(principal: Auditor) -> dict[str, Any]:
        return {"cases": get_service().store.list_failure_cases(False, 100, principal.tenant_id)}

    def list_audit(principal: Auditor, limit: Annotated[int, Query()] = 100) -> dict[str, Any]:
        return {"events": get_service().store.list_audit(principal.tenant_id, limit)}

    def list_alerts(principal: Reader) -> dict[str, Any]:
        return {"alerts": get_service().store.list_alerts(principal.tenant_id)}

    # ----------------------------- 审查任务 -----------------------------

    def create_review(
        principal: Reviewer,
        body: ReviewBody,
        async_: Annotated[str, Query(alias="async")] = "false",
    ) -> Response:
        current = get_service()
        args = (body.repository, body.diff, body.pull_request)
        options = {
            "tenant_id": principal.tenant_id,
            "mode": body.mode,
            "repository_root": body.repository_root,
            "enabled_agents": body.enabled_agents,
            "enabled_skills": body.enabled_skills,
        }
        if async_.lower() == "true":
            response = EvoJSONResponse(current.enqueue_review(*args, **options), status_code=202)
        else:
            response = EvoJSONResponse(current.create_review(*args, **options), status_code=201)
        audit(principal, "review.create", body.repository, {"async": async_, "mode": body.mode})
        return response

    def get_task(principal: Reader, task_id: TaskId) -> dict[str, Any]:
        task = get_service().store.get(task_id, principal.tenant_id)
        if not task:
            raise HTTPException(404, "task not found")
        return task

    def get_report(principal: Reader, task_id: TaskId) -> Response:
        task = get_service().store.get(task_id, principal.tenant_id)
        if not task or not task.get("report"):
            raise HTTPException(404, "task or report not found")
        return Response(to_markdown(task["report"]), media_type="text/markdown; charset=utf-8")

    def list_feedback(principal: Reviewer, task_id: TaskId) -> dict[str, Any]:
        current = get_service()
        if not current.store.get(task_id, principal.tenant_id):
            raise HTTPException(404, "task not found")
        return {"cases": current.store.list_task_failure_cases(task_id, principal.tenant_id)}

    def record_feedback(principal: Reviewer, task_id: TaskId, body: FeedbackBody) -> dict[str, Any]:
        result = get_service().record_feedback(
            task_id, body.category, body.finding, body.note, principal.tenant_id,
        )
        audit(principal, "feedback.record", task_id, {"category": result["category"]})
        return result

    def create_fix(principal: Fixer, task_id: TaskId, body: FixBody | None = None) -> dict[str, Any]:
        installation_id = body.installation_id if body else None
        result = get_service().create_fix(task_id, installation_id, principal.tenant_id)
        audit(principal, "repair.create", task_id, {"branch": result.get("branch")})
        return result

    def cancel_task(principal: Reviewer, task_id: TaskId) -> Response:
        ok = get_service().cancel_task(task_id, principal.tenant_id)
        audit(principal, "task.cancel", task_id)
        return EvoJSONResponse({"cancel_requested": ok}, status_code=202 if ok else 404)

    def resume_task(principal: Reviewer, task_id: TaskId) -> dict[str, Any]:
        result = get_service().resume_task(task_id, principal.tenant_id)
        audit(principal, "task.resume", task_id)
        return result

    # ----------------------------- GitHub -----------------------------

    def github_webhook(
        body: Annotated[bytes, Depends(raw_body)],
        x_github_event: Annotated[str, Header()] = "",
        x_hub_signature_256: Annotated[str, Header()] = "",
        x_github_delivery: Annotated[str, Header()] = "",
    ) -> Any:
        """Webhook 使用 HMAC 签名而非用户 Token 认证，并拒绝重放窗口之外的事件。"""
        if x_github_event != "pull_request":
            return EvoJSONResponse({"ignored": True, "reason": "unsupported GitHub event"}, status_code=202)
        if not settings.github_webhook_secret:
            return error(503, "GitHub webhook secret is not configured")
        if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
            return error(401, "invalid webhook signature")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("request body must be valid UTF-8 JSON")
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object")
        updated_at = (payload.get("pull_request") or {}).get("updated_at")
        if updated_at:
            try:
                event_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("invalid pull_request.updated_at")
            age = abs((datetime.now(timezone.utc) - event_time).total_seconds())
            if age > settings.webhook_max_age_seconds:
                return error(409, "webhook is outside the replay window")
        digest = hashlib.sha256(body).hexdigest()
        return EvoJSONResponse(
            get_service().handle_github_pull_request(payload, x_github_delivery, digest),
            status_code=202,
        )

    def github_install(_: Reader) -> Response:
        if not settings.github_app_slug:
            return error(503, "EVOAGENT_GITHUB_APP_SLUG is not configured")
        return RedirectResponse(
            "https://github.com/apps/%s/installations/new" % settings.github_app_slug, status_code=302
        )

    def github_setup(
        _: Reader,
        installation_id: Annotated[str, Query()] = "",
        account: Annotated[str, Query()] = "github-app",
    ) -> Response:
        try:
            installation = int(installation_id)
        except ValueError:
            return error(400, "missing installation_id")
        get_service().store.save_installation(installation, account)
        return RedirectResponse("/#github", status_code=302)

    # ----------------------------- 运维：发布与队列 -----------------------------

    def get_deployment(principal: Reader) -> dict[str, Any]:
        return {"deployment": get_service().store.get_deployment(principal.tenant_id, "llm-review")}

    def configure_deployment(principal: Manager, body: dict[str, Any]) -> dict[str, Any]:
        result = get_service().releases.configure(principal.tenant_id, "llm-review", body)
        audit(principal, "deployment.configure", "llm-review", body)
        return result

    def list_dead_letters(_: Manager, limit: Annotated[int, Query()] = 100) -> dict[str, Any]:
        return {"messages": get_service().queue.dead_letters(limit)}

    def replay_dead_letter(_: Manager, body: DeadLetterReplayBody) -> Response:
        ok = get_service().queue.replay_dead_letter(body.message_id)
        return EvoJSONResponse({"replayed": ok}, status_code=202 if ok else 404)

    # ----------------------------- Skill 与提示词进化 -----------------------------

    def reload_skills(_: Manager) -> dict[str, Any]:
        return {"skills": get_service().reload_skills(), "note": "New tasks now use the reloaded skill set."}

    def activate_skill_version(_: Manager, name: SkillName, version: Version) -> Response:
        current = get_service()
        ok = current.evolution.rollback(name, version)
        if ok:
            current.reload_skills()
        return EvoJSONResponse({"activated": ok}, status_code=200 if ok else 404)

    def list_evaluation_cases(
        _: Reader, split: Annotated[str, Query()] = "validation",
    ) -> Any:
        if split == "holdout":
            return error(403, "holdout cases are not exposed through the API")
        return {"cases": get_service().store.list_evaluation_cases(split, True, 100)}

    def add_evaluation_case(_: Manager, body: EvaluationCaseBody) -> dict[str, Any]:
        return get_service().evolution.add_evaluation_case(
            body.name, body.diff, body.expected_findings, body.split, "api",
        )

    def evolution_status(_: Reader) -> dict[str, Any]:
        current = get_service()
        status = current.evolution.status()
        status["provider"] = current.llm_config.get("provider", "local")
        status["model"] = current.llm_config.get("model", "")
        return status

    def evolution_runs(_: Reader, limit: Annotated[int, Query()] = 50) -> dict[str, Any]:
        return {"runs": get_service().store.list_evolution_runs(limit)}

    def evolution_auto(principal: Manager, body: EvolutionAutoBody | None = None) -> dict[str, Any]:
        current = get_service()
        result = current.evolution.auto_propose((body or EvolutionAutoBody()).skill_name, principal.tenant_id)
        if result["decision"] == "activated":
            current.reload_skills()
        return result

    def evolution_propose(_: Manager, body: EvolutionProposeBody) -> dict[str, Any]:
        current = get_service()
        result = current.evolution.propose(body.skill_name, body.prompt, body.regression_score)
        if result["decision"] == "activated":
            current.reload_skills()
        return result

    def skill_evolution_status(
        principal: Manager, skill_name: Annotated[str, Query()] = "evolved-review",
    ) -> dict[str, Any]:
        return get_service().skill_evolution.status(skill_name, principal.tenant_id)

    def skill_evolution_runs(principal: Manager, limit: Annotated[int, Query()] = 50) -> dict[str, Any]:
        return {"runs": get_service().store.list_skill_evolution_runs(limit, principal.tenant_id)}

    def skill_artifact_versions(principal: Manager, name: ArtifactName) -> dict[str, Any]:
        return {"versions": get_service().store.list_skill_artifact_versions(name, principal.tenant_id)}

    def skill_evolution_auto(principal: Manager, body: SkillEvolutionAutoBody | None = None) -> dict[str, Any]:
        current = get_service()
        skill_name = (body or SkillEvolutionAutoBody()).skill_name
        result = current.skill_evolution.auto_propose(skill_name, principal.tenant_id)
        if result["decision"] == "activated":
            current.reload_skills()
        audit(principal, "skill.evolution.auto", skill_name,
              {"decision": result["decision"], "run_id": result.get("run_id")})
        return result

    def skill_evolution_propose(principal: Manager, body: SkillEvolutionProposeBody) -> dict[str, Any]:
        current = get_service()
        result = current.skill_evolution.propose(body.skill_name, body.resolved_artifact(), principal.tenant_id)
        if result["decision"] == "activated":
            current.reload_skills()
        audit(principal, "skill.evolution.propose", body.skill_name,
              {"decision": result["decision"], "run_id": result.get("run_id")})
        return result

    def activate_skill_artifact(principal: Manager, name: ArtifactName, version: Version) -> Response:
        current = get_service()
        ok = current.skill_evolution.rollback(name, version, principal.tenant_id)
        if ok:
            current.reload_skills()
        audit(principal, "skill.evolution.activate", name, {"version": version, "activated": ok})
        return EvoJSONResponse({"activated": ok}, status_code=200 if ok else 404)

    # ======================= 中间件、异常与路由集中注册 =======================

    app.middleware("http")(guard)
    app.exception_handler(Unauthorized)(unauthorized)
    app.exception_handler(PermissionError)(forbidden)
    app.exception_handler(ValueError)(bad_request)
    app.exception_handler(RequestValidationError)(invalid_request)
    app.exception_handler(StarletteHTTPException)(http_error)
    app.exception_handler(Exception)(server_error)

    # 管理台静态页面
    app.get("/", include_in_schema=False)(index)
    app.get("/assets/{name}", include_in_schema=False)(asset)

    # 系统与认证
    app.get("/health")(health)
    app.get("/metrics")(prometheus)
    app.post("/v1/auth/login")(login)

    # 管理台数据
    app.get("/api/dashboard")(dashboard)
    app.get("/api/tasks")(list_tasks)
    app.get("/api/skills")(list_skills)
    app.get("/api/failures")(list_failures)
    app.get("/api/audit")(list_audit)
    app.get("/api/alerts")(list_alerts)

    # 审查任务
    app.post("/v1/reviews")(create_review)
    app.get("/v1/tasks/{task_id}")(get_task)
    app.get("/v1/tasks/{task_id}/report")(get_report)
    app.get("/v1/tasks/{task_id}/feedback")(list_feedback)
    app.post("/v1/tasks/{task_id}/feedback", status_code=201)(record_feedback)
    app.post("/v1/tasks/{task_id}/fix", status_code=201)(create_fix)
    app.post("/v1/tasks/{task_id}/cancel")(cancel_task)
    app.post("/v1/tasks/{task_id}/resume", status_code=202)(resume_task)

    # GitHub
    app.post("/webhooks/github")(github_webhook)
    app.get("/github/install")(github_install)
    app.get("/github/setup")(github_setup)

    # 运维：灰度发布与死信队列
    app.get("/api/deployments/llm-review")(get_deployment)
    app.post("/v1/deployments/llm-review", status_code=201)(configure_deployment)
    app.get("/api/queue/dead-letters")(list_dead_letters)
    app.post("/v1/queue/dead-letters/replay")(replay_dead_letter)

    # Skill 管理与提示词进化
    app.post("/v1/skills/reload")(reload_skills)
    app.post("/v1/skills/{name}/versions/{version}/activate")(activate_skill_version)
    app.get("/v1/evaluation/cases")(list_evaluation_cases)
    app.post("/v1/evaluation/cases", status_code=201)(add_evaluation_case)
    app.get("/v1/evolution/status")(evolution_status)
    app.get("/v1/evolution/runs")(evolution_runs)
    app.post("/v1/evolution/auto", status_code=201)(evolution_auto)
    app.post("/v1/evolution/propose", status_code=201)(evolution_propose)

    # Agent Skill artifact 进化
    app.get("/v1/skill-evolution/status")(skill_evolution_status)
    app.get("/v1/skill-evolution/runs")(skill_evolution_runs)
    app.post("/v1/skill-evolution/auto", status_code=201)(skill_evolution_auto)
    app.post("/v1/skill-evolution/propose", status_code=201)(skill_evolution_propose)
    app.get("/v1/skill-evolution/{name}/versions")(skill_artifact_versions)
    app.post("/v1/skill-evolution/{name}/versions/{version}/activate")(activate_skill_artifact)

    return app


def run() -> None:
    """`python -m evoagent` 的入口：读取环境配置并以 uvicorn 启动服务。"""
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, server_header=False)

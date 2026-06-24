"""Session and research-goal HTTP routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, status


def register_sessions_routes(app: FastAPI, host: Any) -> None:
    router = APIRouter()
    auth = [Depends(host.require_auth)]
    event_auth = [Depends(host.require_event_stream_auth)]

    router.add_api_route(
        "/sessions",
        host.create_session,
        methods=["POST"],
        response_model=host.SessionResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions",
        host.list_sessions,
        methods=["GET"],
        response_model=list[host.SessionResponse],
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}",
        host.get_session,
        methods=["GET"],
        response_model=host.SessionResponse,
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/goal",
        host.create_session_goal,
        methods=["POST"],
        response_model=host.GoalSnapshotResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/goal",
        host.get_session_goal,
        methods=["GET"],
        response_model=host.GoalSnapshotResponse,
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/goal",
        host.update_session_goal,
        methods=["PATCH"],
        response_model=host.UpdateGoalResponse,
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/goal/evidence",
        host.add_session_goal_evidence,
        methods=["POST"],
        response_model=host.AddGoalEvidenceResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/goal/status",
        host.update_session_goal_status,
        methods=["PATCH"],
        response_model=host.UpdateGoalStatusResponse,
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}",
        host.delete_session,
        methods=["DELETE"],
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}",
        host.update_session,
        methods=["PATCH"],
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/messages",
        host.send_message,
        methods=["POST"],
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/cancel",
        host.cancel_session,
        methods=["POST"],
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/messages",
        host.get_messages,
        methods=["GET"],
        response_model=list[host.MessageResponse],
        dependencies=auth,
    )
    router.add_api_route(
        "/sessions/{session_id}/events",
        host.session_events,
        methods=["GET"],
        dependencies=event_auth,
    )
    app.include_router(router)

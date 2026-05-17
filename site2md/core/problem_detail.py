from typing import TypedDict


class ProblemDetail(TypedDict, total=False):
    type: str
    title: str
    status: int
    detail: str
    instance: str

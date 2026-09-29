import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from shop_platform.web import ApiError, IdempotencyKey

from orders.domain import (
    DuplicatePaymentReference,
    InvalidOrder,
    OrderError,
    OrderNotCancellable,
    OrderNotFound,
)
from orders.schemas import CancelRequest, OrderListResponse, OrderResponse, PlaceOrderRequest
from orders.service import OrderService

logger = logging.getLogger(__name__)

router = APIRouter()

_STATUS_FOR_ERROR: dict[type[OrderError], int] = {
    OrderNotFound: status.HTTP_404_NOT_FOUND,
    InvalidOrder: status.HTTP_422_UNPROCESSABLE_CONTENT,
    DuplicatePaymentReference: status.HTTP_409_CONFLICT,
    OrderNotCancellable: status.HTTP_409_CONFLICT,
}


def get_service(request: Request) -> OrderService:
    return request.app.state.service


Service = Annotated[OrderService, Depends(get_service)]


def api_error(exc: OrderError) -> ApiError:
    for error_type, http_status in _STATUS_FOR_ERROR.items():
        if isinstance(exc, error_type):
            return ApiError(http_status, exc.code, exc.message)
    logger.error("unmapped order error", extra={"code": exc.code})
    return ApiError(status.HTTP_500_INTERNAL_SERVER_ERROR, exc.code, exc.message)


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def place_order(
    body: PlaceOrderRequest, key: IdempotencyKey, service: Service, response: Response
) -> OrderResponse:
    try:
        order, created = service.place_order(body, key)
    except OrderError as exc:
        raise api_error(exc) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return OrderResponse.of(order)


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, service: Service) -> OrderResponse:
    try:
        return OrderResponse.of(service.get_order(order_id))
    except OrderError as exc:
        raise api_error(exc) from exc


@router.get("/customers/{customer_id}/orders", response_model=OrderListResponse)
def list_orders(
    customer_id: str, service: Service, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> OrderListResponse:
    orders = service.list_orders(customer_id, limit)
    return OrderListResponse(orders=[OrderResponse.of(order) for order in orders])


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(order_id: str, body: CancelRequest, service: Service) -> OrderResponse:
    try:
        return OrderResponse.of(service.cancel_order(order_id, body.reason))
    except OrderError as exc:
        raise api_error(exc) from exc

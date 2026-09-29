FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir "shop-platform @ git+https://github.com/sooraj-dube/shop-platform@v0.3.0"
COPY pyproject.toml README.md ./
COPY orders ./orders
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "orders.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

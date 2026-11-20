FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY campus ./campus
COPY elearning_native ./elearning_native
COPY uv_questionnaires ./uv_questionnaires
COPY templates ./templates
COPY static ./static
RUN python -c "from campus.web import create_app"
EXPOSE 10000
CMD ["gunicorn", "--config", "campus/gunicorn_conf.py", "campus.web:create_app()"]

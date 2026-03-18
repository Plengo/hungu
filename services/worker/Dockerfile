FROM python:3.10-slim
# Install lightweight scraping deps (no Playwright — uses stdlib urllib + bs4)
RUN pip install --no-cache-dir beautifulsoup4 lxml
COPY . /app
WORKDIR /app
CMD ["python", "main.py"]
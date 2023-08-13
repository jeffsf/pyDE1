from pyde1_pyde1

USER root
RUN pip install "pytest>=7.2.1" "pytest-asyncio>=0.20.3"

ADD tests ./tests
ADD pytest.ini .

CMD ["pytest"]

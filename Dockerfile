FROM python:3.14-alpine AS build
WORKDIR /usr/src/app
COPY . .

RUN pip install --upgrade build
RUN python -m build --sdist --wheel .

FROM python:3.14-alpine AS dist
ARG EAG_TAG
WORKDIR /usr/src/app
COPY --from=build /usr/src/app/dist .
COPY --from=build /usr/src/app/docker-scripts/entrypoint.sh .
COPY --from=build /usr/src/app/docker-scripts/sync.sh .
RUN pip install eero_adguard_sync-$EAG_TAG-py3-none-any.whl
RUN chmod +x entrypoint.sh
RUN chmod +x sync.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["crond", "-f"]
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE=
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
ENV API_UPSTREAM=api:8000
COPY deploy/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=4s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

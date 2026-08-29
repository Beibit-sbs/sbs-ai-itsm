FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build
WORKDIR /app
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY package*.json ./
RUN npm config set registry https://registry.npmjs.org/ \
	&& npm config set fetch-retries 5 \
	&& npm config set fetch-retry-mintimeout 20000 \
	&& npm config set fetch-retry-maxtimeout 120000 \
	&& npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
USER root
RUN apk upgrade --no-cache libcrypto3 libssl3 \
	&& apk del --no-cache curl
USER 101
ENV NGINX_ENVSUBST_FILTER="^(TLS_PROXY_CIDR|API_RATE_LIMIT|API_BURST|API_CONNECTION_LIMIT|LOGIN_RATE_LIMIT|LOGIN_RATE_BURST)$" \
    TLS_PROXY_CIDR="127.0.0.1/32" \
    API_RATE_LIMIT="300r/s" \
    API_BURST="600" \
    API_CONNECTION_LIMIT="200" \
    LOGIN_RATE_LIMIT="5r/s" \
    LOGIN_RATE_BURST="10"
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080

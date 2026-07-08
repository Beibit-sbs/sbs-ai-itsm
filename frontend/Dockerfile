FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY package*.json ./
RUN npm config set registry https://registry.npmjs.org/ \
	&& npm config set fetch-retries 5 \
	&& npm config set fetch-retry-mintimeout 20000 \
	&& npm config set fetch-retry-maxtimeout 120000 \
	&& npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080

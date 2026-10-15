FROM node:20 AS build
COPY package.json .
RUN npm ci
FROM node:20-slim
COPY --from=build /app /app
EXPOSE 80

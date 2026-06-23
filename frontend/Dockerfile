FROM node:22-alpine AS base

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Build
COPY . .
ARG NEXT_PUBLIC_BACKEND_BASE=
ENV NEXT_PUBLIC_BACKEND_BASE=$NEXT_PUBLIC_BACKEND_BASE
RUN npm run build

# Production
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=base /app/.next/standalone ./
COPY --from=base /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]

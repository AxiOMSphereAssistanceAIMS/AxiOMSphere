# Deployment Infrastructure Guide — AIMS Self-Support Architecture

**Quick Start**: Follow the checklists below to deploy the complete self-improving system.

---

## 📋 Pre-Deployment Checklist

### 1. Infrastructure Assessment
- [ ] Kubernetes cluster available (or Docker host)
- [ ] 4GB RAM available for system
- [ ] Sufficient disk space (100GB+ recommended for logs/models)
- [ ] Network connectivity verified
- [ ] Security group/firewall rules reviewed

### 2. Access & Credentials
- [ ] AWS account access (for Bedrock)
- [ ] SSH access to deployment target
- [ ] Docker registry credentials (if applicable)
- [ ] Git access to repository

### 3. Team Preparation
- [ ] DevOps team notified
- [ ] On-call rotation set up
- [ ] Runbooks in place
- [ ] Monitoring team briefed

---

## 🚀 Quick Start (Development Mode)

### No Redis, No Bedrock — Just Run It

```bash
# 1. Clone repo (already done)
cd /home/axi_omi_sphere/aims-workspace

# 2. Create virtualenv (if needed)
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install fastapi uvicorn pydantic python-dotenv pyyaml httpx

# 4. Start the API server
python3 -m uvicorn ops.logi.logi_api:app --host 0.0.0.0 --port 8100

# 5. Test the API
curl http://localhost:8100/api/logi/status
```

**Result**: 🟢 API running in in-memory mode
- ProjectStateManager: in-memory
- EventBus: in-memory
- Status API: fully functional

---

## 🐳 Staging Deployment (With Redis)

### Using Docker Compose

```bash
# 1. Install Docker and Docker Compose
# (Skip if already installed)

# 2. Create docker-compose-logi.yml
cat > docker-compose-logi.yml <<'EOF'
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  logi-api:
    build: .
    ports:
      - "8100:8100"
    environment:
      REDIS_URL: redis://redis:6379
      AIMS_PHASE5_EVENTBUS_ENABLED: "true"
    depends_on:
      redis:
        condition: service_healthy
    command: python -m uvicorn ops.logi.logi_api:app --host 0.0.0.0 --port 8100

volumes:
  redis_data:

networks:
  default:
    name: aims-logi
EOF

# 3. Start services
docker-compose -f docker-compose-logi.yml up -d

# 4. Verify Redis is running
docker-compose -f docker-compose-logi.yml logs redis | tail -5

# 5. Test the API
curl http://localhost:8100/api/logi/status

# 6. Check Redis connectivity
docker exec aims-logi-redis-1 redis-cli ping
```

**Result**: 🟢 Full system with Redis
- ProjectStateManager: Redis-backed
- EventBus: Redis pub/sub
- Status API: fully functional
- Persistence: enabled

---

## ⚙️ Production Deployment

### Option A: Kubernetes (Recommended)

```yaml
# 1. Create namespace
apiVersion: v1
kind: Namespace
metadata:
  name: aims

---

# 2. Redis Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: aims
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        volumeMounts:
        - name: redis-data
          mountPath: /data
      volumes:
      - name: redis-data
        persistentVolumeClaim:
          claimName: redis-pvc

---

# 3. Logi API Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: logi-api
  namespace: aims
spec:
  replicas: 2
  selector:
    matchLabels:
      app: logi-api
  template:
    metadata:
      labels:
        app: logi-api
    spec:
      containers:
      - name: logi-api
        image: aims/logi-api:latest
        ports:
        - containerPort: 8100
        env:
        - name: REDIS_URL
          value: redis://redis:6379
        - name: AIMS_PHASE5_EVENTBUS_ENABLED
          value: "true"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8100
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /api/logi/status
            port: 8100
          initialDelaySeconds: 5
          periodSeconds: 5

---

# 4. Service
apiVersion: v1
kind: Service
metadata:
  name: logi-api
  namespace: aims
spec:
  selector:
    app: logi-api
  ports:
  - port: 8100
    targetPort: 8100
  type: LoadBalancer

---

# 5. PersistentVolumeClaim for Redis
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: redis-pvc
  namespace: aims
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

**Deployment**:
```bash
# Apply manifests
kubectl apply -f aims-namespace.yaml
kubectl apply -f redis-deployment.yaml
kubectl apply -f logi-api-deployment.yaml

# Verify
kubectl get pods -n aims
kubectl logs -n aims deployment/logi-api

# Port forward for testing
kubectl port-forward -n aims svc/logi-api 8100:8100
```

### Option B: Docker Swarm

```bash
# 1. Initialize swarm
docker swarm init

# 2. Deploy stack
docker stack deploy -c docker-compose-logi.yml aims

# 3. Verify
docker service ls
docker service logs aims_logi-api
```

### Option C: Bare Metal

```bash
# 1. Install Redis
sudo apt-get install redis-server

# 2. Start Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 3. Deploy app
cd /app/aims-workspace
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Start app with systemd
sudo tee /etc/systemd/system/aims-logi.service <<'EOF'
[Unit]
Description=AIMS Logi API
After=network.target redis-server.service

[Service]
Type=simple
User=aims
WorkingDirectory=/app/aims-workspace
ExecStart=/app/aims-workspace/venv/bin/python -m uvicorn ops.logi.logi_api:app --host 0.0.0.0 --port 8100
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable aims-logi
sudo systemctl start aims-logi
```

---

## 🔐 Security Configuration

### 1. Environment Variables (.env)

```bash
# Create .env file
cat > .env <<'EOF'
# Database
REDIS_URL=redis://localhost:6379

# AWS Bedrock (optional)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=***
AWS_SECRET_ACCESS_KEY=***

# AIMS Configuration
AIMS_PHASE5_EVENTBUS_ENABLED=true
AIMS_PHASE5_EVENTBUS_REDIS_URL=redis://localhost:6379

# Monitoring
LOG_LEVEL=INFO
EOF

# Restrict permissions
chmod 600 .env

# Load in production
export $(cat .env | grep -v '^#' | xargs)
```

### 2. Network Security

```bash
# Firewall rules
sudo ufw allow 6379/tcp   # Redis (internal only)
sudo ufw allow 8100/tcp   # Logi API (external)

# Redis bind to localhost only (in redis.conf)
bind 127.0.0.1
requirepass your_secure_password
```

### 3. Secrets Management

```bash
# Option 1: AWS Secrets Manager
aws secretsmanager create-secret \
  --name aims/production/redis-password \
  --secret-string "your-secure-password"

# Option 2: Kubernetes Secrets
kubectl create secret generic redis-credentials \
  --from-literal=password=your-secure-password \
  -n aims

# Option 3: HashiCorp Vault
vault write secret/aims/redis password=your-secure-password
```

---

## 📊 Monitoring Setup

### 1. Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'logi-api'
    static_configs:
      - targets: ['localhost:8100']
    metrics_path: '/api/logi/metrics'
```

### 2. Alerting Rules

```yaml
# alerts.yml
groups:
  - name: aims
    rules:
      - alert: LogiAPIDown
        expr: up{job="logi-api"} == 0
        for: 5m
        annotations:
          summary: "Logi API is down"

      - alert: HighTaskBlockRate
        expr: (blocked_tasks / total_tasks) > 0.5
        for: 10m
        annotations:
          summary: "High task blocking rate"

      - alert: RedisDown
        expr: redis_up == 0
        for: 5m
        annotations:
          summary: "Redis is down"
```

### 3. Grafana Dashboard

```bash
# Create dashboard
curl -X POST http://localhost:3000/api/dashboards/db \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @grafana-dashboard.json
```

---

## 🧪 Post-Deployment Testing

### 1. Health Check

```bash
# Check API health
curl http://localhost:8100/health

# Check Redis connectivity
redis-cli ping

# Check event publishing
curl http://localhost:8100/api/logi/events/stats
```

### 2. E2E Test

```bash
# Create a test incident
python3 << 'EOF'
import requests
import json

# Create repair task
response = requests.post("http://localhost:8100/api/logi/tasks", json={
    "task_type": "repair",
    "title": "Test repair",
    "created_by": "test",
    "priority": 90
})
print(f"Task created: {response.json()['task_id']}")

# Get status
response = requests.get("http://localhost:8100/api/logi/status")
print(f"Project status: {json.dumps(response.json(), indent=2)}")
EOF
```

### 3. Load Test

```bash
# Install locust
pip install locust

# Create locustfile.py
cat > locustfile.py <<'EOF'
from locust import HttpUser, task, between

class LogiUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def status(self):
        self.client.get("/api/logi/status")
    
    @task
    def metrics(self):
        self.client.get("/api/logi/metrics")
EOF

# Run load test
locust -f locustfile.py -u 100 -r 10 -H http://localhost:8100
```

---

## 🆘 Troubleshooting

### Issue: Redis Connection Failed

```bash
# Check Redis is running
redis-cli ping

# Check connection string
echo $REDIS_URL

# Verify firewall
nc -zv localhost 6379
```

### Issue: API Not Responding

```bash
# Check logs
docker logs aims_logi-api-1
# or
journalctl -u aims-logi -f

# Verify process is running
ps aux | grep logi

# Check port is listening
netstat -tuln | grep 8100
```

### Issue: High Memory Usage

```bash
# Check Redis memory
redis-cli info memory

# Monitor API
docker stats aims_logi-api-1

# Clear Redis if needed
redis-cli FLUSHALL  # WARNING: Deletes all data
```

---

## ✅ Deployment Verification Checklist

- [ ] Redis running and responsive
- [ ] Logi API started on port 8100
- [ ] Health check passing
- [ ] Status API returning data
- [ ] EventBus events being published
- [ ] ProjectStateManager persisting tasks
- [ ] Monitoring and alerting configured
- [ ] Backup strategy in place
- [ ] Documentation updated
- [ ] Team trained on operations

---

## 🔄 Ongoing Operations

### Daily Tasks

- [ ] Check system health dashboard
- [ ] Review error logs
- [ ] Verify incident processing
- [ ] Monitor resource usage

### Weekly Tasks

- [ ] Review performance metrics
- [ ] Check for capacity issues
- [ ] Test backup recovery
- [ ] Review security logs

### Monthly Tasks

- [ ] Full system audit
- [ ] Capacity planning
- [ ] Update runbooks
- [ ] Security review

---

## 📞 Support Contacts

- **Ops On-Call**: [contact info]
- **Escalation**: [contact info]
- **Emergency**: [contact info]

---

**Document Version**: 1.0
**Last Updated**: June 3, 2026
**Status**: Ready for Production Deployment

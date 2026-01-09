# 身份认证使用说明

## 概述

本项目使用 HTTP Basic Authentication 保护以下接口：

### 受保护的页面
- `/admin` - 管理页面
- `/remote` - 远程控制页面

### 受保护的 API
- `/api/admin/*` - 所有管理 API 接口

## 配置认证信息

认证信息读取优先级：**环境变量 > 数据库配置 > 默认值**

### 方法 1: 通过环境变量（推荐）

在 `.env` 文件中设置：

```bash
ADMIN_USERNAME=your_username
ADMIN_PASSWORD=your_secure_password
```

或者在启动时设置环境变量：

```bash
export ADMIN_USERNAME=your_username
export ADMIN_PASSWORD=your_secure_password
python -m server.app
```

Docker Compose 方式：

```yaml
# docker-compose.yml
services:
  api:
    environment:
      - ADMIN_USERNAME=your_username
      - ADMIN_PASSWORD=your_secure_password
```

### 方法 2: 通过数据库配置

访问 `/api/admin/config` 接口更新配置：

```bash
curl -X PUT http://localhost:8000/api/admin/config \
  -u admin:changeme \
  -H "Content-Type: application/json" \
  -d '{
    "admin_username": "your_username",
    "admin_password": "your_secure_password"
  }'
```

**注意**: 如果设置了环境变量，数据库配置会被忽略。

### 默认账号

- **用户名**: `admin`
- **密码**: `changeme`

⚠️ **重要**: 首次部署后请立即修改默认密码！

## 使用方式

### 浏览器访问

1. 访问 `http://localhost:8000/admin` 或 `http://localhost:8000/remote`
2. 浏览器会自动弹出登录框
3. 输入用户名和密码
4. 登录后浏览器会记住凭证（直到关闭浏览器或清除缓存）

### API 调用

使用 HTTP Basic Auth 调用 API：

```bash
# 方式 1: 使用 -u 参数
curl -u username:password http://localhost:8000/api/admin/browsers

# 方式 2: 使用 Authorization header
curl -H "Authorization: Basic $(echo -n 'username:password' | base64)" \
  http://localhost:8000/api/admin/browsers
```

### Python 代码示例

```python
import requests
from requests.auth import HTTPBasicAuth

# 方式 1: 使用 auth 参数
response = requests.get(
    "http://localhost:8000/api/admin/browsers",
    auth=HTTPBasicAuth("username", "password")
)

# 方式 2: 使用 Session 保持认证
session = requests.Session()
session.auth = HTTPBasicAuth("username", "password")
response = session.get("http://localhost:8000/api/admin/browsers")
```

### JavaScript/Fetch 示例

```javascript
// 在 fetch 中使用 Basic Auth
const username = 'your_username';
const password = 'your_password';
const credentials = btoa(`${username}:${password}`);

fetch('http://localhost:8000/api/admin/browsers', {
  headers: {
    'Authorization': `Basic ${credentials}`
  }
})
.then(response => response.json())
.then(data => console.log(data));
```

## 安全建议

1. ✅ **立即修改默认密码** - 使用强密码（至少 12 位，包含大小写字母、数字和特殊字符）
2. ✅ **使用 HTTPS** - 在生产环境中务必使用 HTTPS，否则密码会明文传输
3. ✅ **定期更换密码** - 建议每 3-6 个月更换一次密码
4. ✅ **限制网络访问** - 使用防火墙或反向代理限制管理接口的访问来源
5. ✅ **监控访问日志** - 定期检查 `/api/admin/logs` 查看访问记录

## 使用 Nginx 反向代理增强安全性

可以在 Nginx 层面添加额外的安全措施：

```nginx
# 限制 /admin 和 /api/admin 的访问来源
location ~ ^/(admin|api/admin) {
    # 只允许特定 IP 访问
    allow 192.168.1.0/24;
    deny all;

    # 传递给后端
    proxy_pass http://backend;
}

# 速率限制
limit_req_zone $binary_remote_addr zone=admin:10m rate=10r/m;

location /api/admin {
    limit_req zone=admin burst=5;
    proxy_pass http://backend;
}
```

## 故障排查

### 401 Unauthorized 错误

- 检查用户名和密码是否正确
- 确认配置已正确加载（查看日志或访问 `/api/admin/config`）
- 检查是否使用了正确的认证方式（HTTP Basic Auth）

### 浏览器未弹出登录框

- 检查浏览器是否缓存了旧的凭证（清除浏览器缓存）
- 尝试使用隐私/无痕模式访问
- 检查响应头中是否包含 `WWW-Authenticate: Basic`

### API 调用失败

- 确认 Authorization header 格式正确
- 检查 base64 编码是否正确
- 使用 curl -v 查看详细的请求和响应信息

## 实现细节

### 文件结构

```
server/
├── auth.py           # 认证模块（新增）
├── app.py            # 主应用（已更新，添加认证）
└── api/
    └── management.py # 管理 API（已更新，添加认证）
```

### 工作原理

1. 使用 FastAPI 的 `HTTPBasic` 和 `Depends` 机制
2. `verify_admin()` 函数从配置中读取正确的用户名和密码
3. 使用 `secrets.compare_digest()` 进行常量时间比较，防止时序攻击
4. 认证失败返回 401 状态码，浏览器自动弹出登录框

### 性能影响

- 每次请求都会验证一次用户名和密码（常量时间比较）
- 对性能影响极小（微秒级）
- 浏览器会自动缓存凭证，不需要用户重复输入

## 升级方案

如果未来需要更复杂的认证方案，可以考虑：

1. **JWT Token** - 无状态认证，适合分布式部署
2. **API Key** - 为不同客户端分配不同的密钥
3. **OAuth2** - 支持第三方登录
4. **基于角色的访问控制 (RBAC)** - 不同用户不同权限

当前的 HTTP Basic Auth 方案已经足够简单和安全，适合单用户/小团队使用。

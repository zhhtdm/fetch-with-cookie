# fetch with cookie
内部为一个`playwright`控制的`chromium-headless`浏览器
- 以在保存使用`cookie`环境下并尽量模拟正常浏览器行为来获取网页内容
- 可通过远程调试进行网站登录来更新`cookie`
- 可配置最大网页数、超时时间和重试次数
- 支持 `br` `gzip` 压缩传输

## API
```
http(s)://service.domain/path?token=your-token&url=
```
- `url`参数需要编码转义:
```JavaScript
// js
encodeURIComponent(url)
```
```python
# python
import urllib.parse
urllib.parse.quote(url, safe='')
```
- 服务首次运行时，`playwright`会自动安装依赖，此过程可能长达数分钟
## 远程调试

远程调试服务端口默认为`9222`，默认绑定到`127.0.0.1`，
此时外网不能访问，可以通过 SSH 隧道方式安全访问:
```bash
# 本地执行: ssh -L 本地端口:目标地址:目标端口 user@远程server
ssh -L 9222:localhost:9222 user@server
```
`chrome`访问[`chrome://inspect#devices`](chrome://inspect#devices)，即可在本地浏览器访问远程浏览器的调试页面，SSH 登出时，开启的 SSH 隧道会自动关闭
## 项目环境变量 (.env)
在项目根目录下创建 .env 文件，`TOKEN` 项必须配置，其他项可以省略，示例:
```
TOKEN=abcdef
APP_PATH=""
HOST=127.0.0.1
PORT=9000
REMOTE_DEBUGGING_PORT=9222
REMOTE_DEBUGGING_ADDRESS=127.0.0.1
MAX_CONCURRENT_PAGES=8
PAGE_TIMEOUT=30000
MAX_RETRIES=2
```
- **`TOKEN`: 验证令牌，防止滥用**
- `APP_PATH`: 服务路径，默认为空
- `PORT`: 服务监听端口，默认为 `8000`
- `HOST`: 默认绑定内网 `127.0.0.1`
- `REMOTE_DEBUGGING_PORT`: 远程调试端口，默认为`9222`
- `REMOTE_DEBUGGING_ADDRESS`: 远程调试地址，默认为 `127.0.0.1`
- `MAX_CONCURRENT_PAGES`: 最大同时打开的网页数，默认为 `8`
- `PAGE_TIMEOUT`: 超时时间，单位毫秒，默认为`30000`
- `MAX_RETRIES`: 最大重试数，默认为`2`

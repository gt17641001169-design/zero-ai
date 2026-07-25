"""ZeroAI Proxy 自签证书生成脚本

生成自签证书用于 HTTPS，保护 Token 传输安全。

使用方式：
    python generate_cert.py

生成文件：
    cert.pem  - 证书文件（配置到 SSL_CERT_FILE）
    cert.key  - 私钥文件（配置到 SSL_KEY_FILE）

客户端需手动信任此证书（因为是自签的，不是 CA 签发的）。
"""

import os
import sys
import datetime
from datetime import timezone


def generate_cert():
    """生成自签证书"""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        print("❌ 缺少 cryptography 库，正在安装...")
        os.system(f"{sys.executable} -m pip install cryptography -i https://pypi.tuna.tsinghua.edu.cn/simple")
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

    # 1. 生成私钥（RSA 4096 位）
    print("🔐 生成 RSA 4096 私钥...")
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )

    # 2. 构造证书主题
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Beijing"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Beijing"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ZeroAI"),
        x509.NameAttribute(NameOID.COMMON_NAME, "zeroai-proxy"),
    ])

    # 3. 构造证书（有效期 365 天）
    print("📜 签发证书（有效期 365 天）...")
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(timezone.utc))
        .not_valid_after(datetime.datetime.now(timezone.utc) + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("zeroai-proxy"),
                x509.DNSName("localhost"),
                x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    # 4. 写入文件
    cert_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.pem")
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.key")

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"✅ 证书已生成: {cert_path}")

    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    print(f"✅ 私钥已生成: {key_path}")

    # 5. 提示配置
    print()
    print("=" * 60)
    print("📋 配置说明：")
    print("=" * 60)
    print("在 .env 文件中添加以下配置：")
    print()
    print(f"SSL_CERT_FILE={cert_path}")
    print(f"SSL_KEY_FILE={key_path}")
    print()
    print("⚠️  客户端需手动信任此证书（自签证书不被浏览器/系统默认信任）")
    print("⚠️  请妥善保管 cert.key 私钥文件，不要泄露或上传到 Git")
    print()
    print("客户端访问方式：")
    print("  Python OpenAI SDK: 需设置 verify=False 或指定 CA 证书")
    print("  curl: curl -k https://192.168.10.6:8000/health  # -k 忽略证书验证")


if __name__ == "__main__":
    generate_cert()

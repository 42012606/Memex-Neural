"""
AI 错误信息中文化翻译工具
将 Provider 返回的英文错误信息映射为中文提示
"""
import re
import logging

logger = logging.getLogger(__name__)


def translate_ai_error(error_msg: str) -> str:
    """
    将 AI Provider 错误信息翻译为中文
    
    :param error_msg: 原始错误信息（可能是英文）
    :return: 中文错误提示
    """
    if not error_msg:
        return "未知错误"
    
    error_lower = error_msg.lower()
    
    # API Key 相关错误
    if any(kw in error_lower for kw in [
        "api key not valid", "api key invalid", "invalid api key",
        "api key is invalid", "authentication failed", "unauthorized",
        "401", "api_key", "api key", "authentication", "unauthorized"
    ]):
        if "quota" in error_lower or "limit" in error_lower:
            return "API Key 无效或配额已耗尽"
        return "API Key 无效或未配置"
    
    # 配额/限制相关
    if any(kw in error_lower for kw in [
        "quota", "rate limit", "rate_limit", "too many requests",
        "429", "limit exceeded", "usage limit"
    ]):
        return "API 配额已耗尽或请求频率过高，请稍后重试"
    
    # 模型不存在或不可用
    if any(kw in error_lower for kw in [
        "model not found", "model does not exist", "invalid model",
        "model unavailable", "404"
    ]):
        return "模型不存在或不可用，请检查模型 ID 配置"
    
    # 网络/连接错误
    if any(kw in error_lower for kw in [
        "connection", "timeout", "network", "dns", "resolve",
        "refused", "unreachable", "timed out"
    ]):
        return "网络连接失败，请检查网络设置或代理配置"
    
    # SSL/TLS 错误
    if any(kw in error_lower for kw in [
        "ssl", "tls", "certificate", "handshake", "verify"
    ]):
        return "SSL 证书验证失败，请检查网络代理或证书配置"
    
    # 服务器错误
    if any(kw in error_lower for kw in [
        "500", "502", "503", "504", "internal server error",
        "bad gateway", "service unavailable", "gateway timeout"
    ]):
        return "AI 服务暂时不可用，请稍后重试"
    
    # 请求格式错误
    if any(kw in error_lower for kw in [
        "400", "bad request", "invalid request", "malformed"
    ]):
        return "请求格式错误，请检查配置参数"
    
    # 权限错误
    if any(kw in error_lower for kw in [
        "403", "forbidden", "permission denied", "access denied"
    ]):
        return "权限不足，请检查 API Key 权限设置"
    
    # 内容过滤/安全策略
    if any(kw in error_lower for kw in [
        "safety", "content filter", "blocked", "policy violation",
        "harmful", "unsafe"
    ]):
        return "内容被安全策略过滤，请调整输入内容"
    
    # Gemini 特定错误
    if "google" in error_lower or "gemini" in error_lower:
        if "api key" in error_lower:
            return "Gemini API Key 无效"
        if "quota" in error_lower:
            return "Gemini API 配额已耗尽"
        if "not found" in error_lower:
            return "Gemini 模型不存在"
    
    # OpenAI 特定错误
    if "openai" in error_lower:
        if "api key" in error_lower:
            return "OpenAI API Key 无效"
        if "quota" in error_lower or "billing" in error_lower:
            return "OpenAI 账户余额不足或配额已耗尽"
        if "model" in error_lower and "not found" in error_lower:
            return "OpenAI 模型不存在或不可用"
    
    # Dashscope/Qwen 特定错误
    if "dashscope" in error_lower or "qwen" in error_lower or "aliyun" in error_lower:
        if "api key" in error_lower:
            return "Dashscope API Key 无效"
        if "quota" in error_lower:
            return "Dashscope API 配额已耗尽"
    
    # 通用错误模式匹配
    # 如果包含常见错误关键词但未匹配上述规则，返回通用提示
    if any(kw in error_lower for kw in ["error", "failed", "exception"]):
        # 尝试提取关键信息
        if len(error_msg) > 100:
            return f"AI 服务错误：{error_msg[:50]}..."
        return f"AI 服务错误：{error_msg}"
    
    # 默认返回原错误信息（如果很短）或通用提示
    if len(error_msg) <= 50:
        return f"错误：{error_msg}"
    
    return "AI 服务调用失败，请检查配置和网络连接"


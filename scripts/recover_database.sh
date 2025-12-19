#!/bin/bash
# PostgreSQL 数据库恢复脚本
# 用于修复 WAL 损坏问题

set -e

echo "🔍 检查数据库状态..."

# 停止容器
echo "⏹️  停止数据库容器..."
docker-compose stop db

# 备份当前数据目录（以防万一）
BACKUP_DIR="./data/postgres_backup_$(date +%Y%m%d_%H%M%S)"
if [ -d "./data/postgres" ]; then
    echo "💾 备份当前数据库目录到: $BACKUP_DIR"
    cp -r ./data/postgres "$BACKUP_DIR"
fi

echo ""
echo "请选择恢复方案："
echo "1. 尝试修复 WAL（可能恢复部分数据）"
echo "2. 重新初始化数据库（会丢失所有数据）"
read -p "请输入选项 (1/2): " choice

case $choice in
    1)
        echo "🔧 尝试修复 WAL..."
        docker run --rm \
            -v "$(pwd)/data/postgres:/var/lib/postgresql/data" \
            pgvector/pgvector:pg16 \
            bash -c "pg_resetwal -f /var/lib/postgresql/data"
        
        echo "✅ WAL 已重置，尝试启动数据库..."
        docker-compose up -d db
        
        echo "⏳ 等待数据库启动..."
        sleep 5
        
        # 检查数据库状态
        if docker exec memex-db pg_isready -U memex > /dev/null 2>&1; then
            echo "✅ 数据库已成功启动！"
            echo "⚠️  请检查数据完整性，建议立即备份！"
        else
            echo "❌ 数据库启动失败，可能需要重新初始化"
            echo "请运行选项 2 重新初始化数据库"
        fi
        ;;
    2)
        echo "⚠️  警告：这将删除所有数据库数据！"
        read -p "确认重新初始化？(yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            echo "🗑️  删除损坏的数据库目录..."
            rm -rf ./data/postgres/*
            rm -rf ./data/postgres/.* 2>/dev/null || true
            
            echo "🔄 重新初始化数据库..."
            docker-compose up -d db
            
            echo "⏳ 等待数据库初始化..."
            sleep 10
            
            echo "✅ 数据库已重新初始化！"
            echo "📝 请重新配置模型和设置"
        else
            echo "❌ 操作已取消"
        fi
        ;;
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac



##Useful commands PGSQL

docker exec -it homelab-postgres psql -U postgres -d sklep_backup

docker exec homelab-microservice-orchestrator cat /var/log/microservice_mail/orchestrator.log

docker exec homelab-microservice-orchestrator find / -name "*.log" 2>/dev/null

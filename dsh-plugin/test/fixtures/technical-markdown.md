# Spec: Встроенная административная консоль Better Sidebar

## 1. Intent & Invariants
- What: восстановить `node-pty` и превратить штатную вкладку **Terminal** Better Sidebar во встроенную административную консоль.
- `Verdict: Compose — dsh-better-sidebar + node-pty + loopback OpenSSH — существующий терминал используется без Cockpit и нового PTY-интерфейса.`
- Причина ошибки установлена: Linux-модуль `pty.node` отсутствует, а `pnpm-workspace.yaml` содержит незавершённое разрешение сборки `node-pty`.
- PTY запускает SSH-клиент к отдельному `sshd` на `127.0.0.1:2222`.
- После PAM-пароля SSH выполняет `sudo -i`, и пользователь получает root-shell внутри Sidebar.
- Прямой SSH-вход как `root`, forwarding, tunnel и публичный listener запрещены.
- `dsh-web.service` остаётся пользователем `dsh` с `NoNewPrivileges=yes`.
- Пароль не передаётся через чат, argv, environment, DSH или Git.
- Cockpit, Tailnet endpoint 9090 и `dsh-admin-terminal` удаляются.
- Активный DSH не перезапускается; конфигурация применяется при следующем штатном старте.

## 2. Interface / Data Contract
```yaml
pnpm-workspace:
  allowBuilds:
    node-pty: true

better-sidebar:
  shell: /usr/bin/ssh
  shellArgs:
    - -tt
    - -o
    - PreferredAuthentications=password
    - -o
    - PubkeyAuthentication=no
    - -o
    - StrictHostKeyChecking=yes
    - -p
    - "2222"
    - user@127.0.0.1
    - sudo
    - -i

sidebar-admin-sshd:
  listen: 127.0.0.1:2222
  authentication: PAM-password
  allowUsers: [user]
  permitRootLogin: false
  forwarding: false
  idleRootSession: PTY-owned
```

## 3. Verification Checklist (Definition of Done)
- [ ] `pnpm rebuild node-pty` создаёт Linux `pty.node`.
- [ ] `import('node-pty')` успешно выполняется из Web‑профиля.
- [ ] Отдельный `sshd` проходит `sshd -t` и слушает только `127.0.0.1:2222`.
- [ ] Host key заранее закреплён в `dsh` known_hosts; TOFU отключён.
- [ ] Неверный пароль не открывает SSH-сессию.
- [ ] После скрытой установки пароля вкладка Terminal открывает root-shell.
- [ ] В консоли `id -u` возвращает `0`.
- [ ] Закрытие вкладки завершает SSH/root-сессию.
- [ ] `dsh-web.service` сохраняет прежний PID, пользователя и `NoNewPrivileges=yes`.
- [ ] Cockpit, HTTPS 9090 и launcher-плагин удалены.
- [ ] Better Sidebar остаётся единственной терминальной панелью.
- [ ] Изменения, rollback и ручная установка пароля задокументированы.

Ответьте: **Утвердить / Доработать**

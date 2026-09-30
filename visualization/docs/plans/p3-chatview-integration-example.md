# P3 ChatView Integration Example

展示如何将新的 presentation 层集成到 ChatView。

## 当前状态

- ✅ presentation types 已定义（`presentation.ts`）
- ✅ adapters 已实现（`adapters.ts`）
- ✅ ActivityBuffer 已实现（`activityBuffer.ts`）
- ✅ presentationStore 已创建（`presentationStore.ts`）
- ✅ ActivityStep 组件已创建
- ✅ LiveStatus 组件已创建
- ✅ TurnView 组件已创建

## 集成方案

### 1. WebSocket 事件处理

在 `src/api/websocket.ts` 中集成 ActivityBuffer：

```typescript
import { presentationStore } from "../features/chat/presentationStore";
import { turnStore } from "../store/turnStore";

// 当接收到 ObservationEvent 时
function handleObservationEvent(event: ObservationEvent) {
  const currentTurnId = turnStore.getState().turnId;
  
  if (event.turn_id === currentTurnId) {
    // 当前 Turn 的事件 → 添加到 activity buffer
    presentationStore.getState().addEvent(event);
  } else {
    // 非当前 Turn 的事件 → 只触发 owner refresh
    turnStore.getState().refresh();
  }
}

// 重连后重建 buffer
function handleReconnect() {
  const currentTurnId = turnStore.getState().turnId;
  if (currentTurnId) {
    rebuildActivityBuffer(currentTurnId);
  }
}
```

### 2. Turn 切换时创建 buffer

在 `turnController.ts` 中：

```typescript
import { presentationStore } from "../features/chat/presentationStore";

export async function openTurn(turnId: string) {
  // 切换 Turn
  await turnStore.getState().openTurn(turnId, ...);
  
  // 创建新的 activity buffer
  presentationStore.getState().createBuffer(turnId);
  
  // 如果需要，从 events replay 重建
  if (shouldRebuildBuffer(turnId)) {
    await rebuildActivityBuffer(turnId);
  }
}

export function closeTurn() {
  // 清除 activity buffer
  presentationStore.getState().clearBuffer();
  turnStore.getState().clearTurn();
}
```

### 3. ChatView 中使用 TurnView

当前 `ChatView.tsx` 的 `ConversationView` 部分可以改为：

```typescript
import { TurnView } from "./TurnView";
import { useTurnPresentation } from "./useTurnPresentation";

function ConversationView() {
  const presentation = useTurnPresentation();
  const turnId = useTurnStore((s) => s.turnId);
  
  if (!presentation || !turnId) {
    return <LoadingState />;
  }

  return (
    <div className="conversation-view">
      <TurnView
        presentation={presentation}
        isLatest={true}
        onOpenTrace={() => openTurnProcess(turnId)}
        onStop={() => stopTurn(turnId)}
      />
    </div>
  );
}
```

### 4. 历史 Turn 渲染

对于历史 Turn（Session 中的 Turn），使用相同的 TurnView 但不创建 activity buffer：

```typescript
function HistoryTurnView({ turnId }: { turnId: string }) {
  // 只读取 snapshot，不创建 activity buffer
  const snapshot = await fetchTurnSnapshot(turnId);
  const presentation = snapshotToPresentation(snapshot);
  
  return (
    <TurnView
      presentation={presentation}
      isLatest={false}
      onOpenTrace={() => openTurnProcess(turnId)}
    />
  );
}
```

### 5. 集成检查清单

- [ ] WebSocket onEvent → presentationStore.addEvent
- [ ] WebSocket onReconnect → rebuildActivityBuffer
- [ ] turnController openTurn → createBuffer
- [ ] turnController closeTurn → clearBuffer
- [ ] ChatView ConversationView → TurnView with presentation
- [ ] 历史 Turn 渲染 → TurnView without buffer
- [ ] 测试：新 Turn、追加、回复、停止
- [ ] 测试：重连恢复、gap 标记
- [ ] 测试：历史 Turn 查看

## 渐进式迁移

当前 ChatView 已经有完整实现，可以采用渐进式迁移：

1. **Phase 1**：保留当前 ChatView，添加 presentationStore 后台运行
   - WebSocket 集成 addEvent
   - 不改变当前 UI
   - 验证 presentation 数据正确性

2. **Phase 2**：在当前 ChatView 中局部使用新组件
   - 用 LiveStatus 替换当前的活动状态显示
   - 用 ActivityStep 替换当前的活动步骤显示
   - 保留其他部分不变

3. **Phase 3**：完全迁移到新的 TurnView
   - 移除旧的呈现逻辑
   - 使用 TurnView 作为唯一 Turn 渲染器
   - 移除冗余状态

## 下一步

- 实施 WebSocket 集成
- 实施 turnController 集成
- 创建集成测试
- 渐进式替换当前 ChatView 的组件

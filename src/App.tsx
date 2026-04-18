/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect, useRef } from 'react';
import { 
  Cpu, 
  TrendingUp, 
  TrendingDown, 
  Zap, 
  Play,
  Square,
  MessageSquare,
  Brain,
  CircuitBoard,
  Shield,
  Radio,
  Wifi,
  WifiOff,
  Loader2,
  Globe,
  CheckCircle,
  AlertTriangle,
  Settings,
  X,
  Link as LinkIcon
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';


import io from 'socket.io-client';


// --- Types ---
type SignalType = 'CALL' | 'PUT';
type RobotState = 'IDLE' | 'ANALYZING' | 'PRE_ALERT' | 'CONFIRMED' | 'WIN' | 'LOSS';
type MarketAsset = {
  pair: string;
  payout: number;
};

interface RobotStateData {
  state: RobotState;
  asset?: string;
  type?: SignalType;
  strategy?: string;
  countdown?: number;
  time?: string;
  expiration?: number;
  next_scan_in?: number;
  message?: string;
  timeframe?: number;
}

interface SsidStatusData {
  status: 'IDLE' | 'LAUNCHING' | 'BROWSER_OPEN' | 'WAITING_LOGIN' | 'CAPTURED' | 'CONNECTING' | 'CONNECTED' | 'ERROR';
  message?: string;
}

interface BrokerStatusData {
  connected: boolean;
  ssid_captured: boolean;
}

interface TradeRecord {
  id: string;
  created_at: string;
  asset: string;
  signal_type: 'CALL' | 'PUT';
  strategy: string;
  timeframe: number;
  result: 'WIN' | 'LOSS' | 'PENDING';
  amount: number;
}


const ASSETS: MarketAsset[] = [
  { pair: 'EUR/USD', payout: 87 },
  { pair: 'GBP/JPY', payout: 91 },
  { pair: 'BTC/USDT', payout: 82 },
  { pair: 'USD/JPY', payout: 85 },
  { pair: 'AUD/CAD', payout: 88 },
];

export default function App() {
  const [isActive, setIsActive] = useState(false);
  const [robotState, setRobotState] = useState<RobotState>('IDLE');
  const [currentAsset, setCurrentAsset] = useState<MarketAsset>(ASSETS[0]);
  const [preAlertCountdown, setPreAlertCountdown] = useState(0);
  const [expirationCountdown, setExpirationCountdown] = useState(0);
  const [pendingSignalType, setPendingSignalType] = useState<SignalType | null>(null);
  const [analysisCountdown, setAnalysisCountdown] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [lastSignal, setLastSignal] = useState<{ 
    type: SignalType; 
    pair: string; 
    time: string;
    strategy?: string;
  } | null>(null);
  const [currentStrategy, setCurrentStrategy] = useState<string>('');
  
  // Função para formatar segundos em MM:SS
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };
  
  const [isBridgeConnected, setIsBridgeConnected] = useState(false);
  const [isBrokerConnected, setIsBrokerConnected] = useState(false);
  const [ssidStatus, setSsidStatus] = useState<'IDLE' | 'LAUNCHING' | 'BROWSER_OPEN' | 'WAITING_LOGIN' | 'CAPTURED' | 'CONNECTING' | 'CONNECTED' | 'ERROR'>('IDLE');
  const [ssidMessage, setSsidMessage] = useState('');
  const [isCapturing, setIsCapturing] = useState(false);
  const [timeframe, setTimeframe] = useState<1 | 5>(1);
  const [tradeHistory, setTradeHistory] = useState<TradeRecord[]>([]);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [customBridgeUrl, setCustomBridgeUrl] = useState<string>(() => {
    const saved = localStorage.getItem('profitwave_bridge_url');
    if (saved) return saved;
    // Default to Render URL if we are likely using the cloud version
    if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
      return 'https://profitwaver.onrender.com';
    }
    return '';
  });
  const [manualSsid, setManualSsid] = useState<string>(() => {
    return localStorage.getItem('profitwave_manual_ssid') || '';
  });
  const [serverType, setServerType] = useState<'LOCAL' | 'CLOUD'>(() => {
    if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
      return 'CLOUD';
    }
    return 'LOCAL';
  });
  
  const socketRef = useRef<ReturnType<typeof io> | null>(null);

  const fetchHistory = async () => {
    try {
      const SUPABASE_URL = 'https://vzcixhgdvbnsumtxufto.supabase.co';
      const SUPABASE_ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6Y2l4aGdkdmJuc3VtdHh1ZnRvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY0NjY5NjAsImV4cCI6MjA5MjA0Mjk2MH0.474btqncx8jdA9lFG_2DHcwOSUBFaZeX1pihPstJfUg';
      const res = await fetch(
        `${SUPABASE_URL}/rest/v1/signals?order=created_at.desc&limit=20`,
        { headers: { 'apikey': SUPABASE_ANON, 'Authorization': `Bearer ${SUPABASE_ANON}` } }
      );
      if (res.ok) {
        const data = await res.json();
        setTradeHistory(data);
      }
    } catch (_) {}
  };


  useEffect(() => {
    // SECURITY/CLEANUP: If we are on Vercel and the bridge URL is local or empty, force Render URL
    if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
      const current = localStorage.getItem('profitwave_bridge_url');
      if (!current || current.includes('localhost') || current.includes('127.0.0.1')) {
        console.log("Forcing Render Cloud URL for production environment...");
        setCustomBridgeUrl('https://profitwaver.onrender.com');
        localStorage.setItem('profitwave_bridge_url', 'https://profitwaver.onrender.com');
        setServerType('CLOUD');
      }
    }
  }, []);
  const playSound = (freq: number, duration: number) => {
    // Sound disabled by user request
  };

  useEffect(() => {
    // URL configurável via variável de ambiente (VITE_BRIDGE_URL) ou campo customizado
    // No Vercel: o usuário pode colar a URL do ngrok no modal de configurações
    const BRIDGE_URL = customBridgeUrl || import.meta.env.VITE_BRIDGE_URL || 'http://127.0.0.1:5001';
    
    console.log(`Connecting to Bridge at: ${BRIDGE_URL}`);

    socketRef.current = io(BRIDGE_URL, {
      transports: ['websocket', 'polling'],
      reconnectionAttempts: 5,
      timeout: 10000
    });

    socketRef.current.on('connect', () => {
      console.log('--- BRIDGE CONNECTED ---');
      setIsBridgeConnected(true);
    });

    socketRef.current.on('server_status', (data: { status: string; type: 'LOCAL' | 'CLOUD' }) => {
      setServerType(data.type);
    });

    socketRef.current.on('connect_error', (err: Error) => {
      console.error('Socket Connection Error:', err);
      setIsBridgeConnected(false);
    });

    // SSID capture status updates
    socketRef.current.on('ssid_status', (data: SsidStatusData) => {
      console.log('SSID Status:', data);
      setSsidStatus(data.status);
      setSsidMessage(data.message || '');
      if (data.status === 'CONNECTED') {
        setIsCapturing(false);
        setIsBrokerConnected(true);
        playSound(880, 0.3);
      } else if (data.status === 'ERROR') {
        setIsCapturing(false);
        playSound(220, 0.4);
      } else if (data.status === 'LAUNCHING' || data.status === 'BROWSER_OPEN' || data.status === 'WAITING_LOGIN' || data.status === 'CAPTURED' || data.status === 'CONNECTING') {
        setIsCapturing(true);
      }
    });

    // Broker connection status
    socketRef.current.on('broker_status', (data: BrokerStatusData) => {
      setIsBrokerConnected(data.connected);
    });

    socketRef.current.on('disconnect', () => {
      console.log('--- BRIDGE DISCONNECTED ---');
      setIsBridgeConnected(false);
      setRobotState('IDLE');
    });

    socketRef.current.on('heartbeat', (data: { time: number }) => {
      console.log('Heartbeat from Bridge:', data.time);
    });

    socketRef.current.on('robot_state', (data: RobotStateData) => {
      if (!isActive) return;

      const { state, asset, type, strategy, countdown, time, expiration, next_scan_in, message } = data;
      setRobotState(state);
      
      if (asset) {
        setCurrentAsset({ pair: asset, payout: 87 }); // Default payout for now
      }

      if (message) setStatusMessage(message);
      if (next_scan_in !== undefined) setAnalysisCountdown(next_scan_in);
      
      // Sincronizar expiração globalmente se enviada
      if (expiration) {
        setExpirationCountdown(expiration);
      } else if (state === 'IDLE' || state === 'ANALYZING') {
        // Fallback para o tempo do timeframe selecionado
        setExpirationCountdown(timeframe * 60);
      }

      if (state === 'ANALYZING') {
        playSound(440, 0.2);
      }

      if (state === 'PRE_ALERT') {
        setPendingSignalType(type || null);
        setPreAlertCountdown(countdown || 15);
        if (strategy) setCurrentStrategy(strategy);
        playSound(660, 0.1);
      }

      if (state === 'CONFIRMED') {
        if (type && asset && time) {
          setLastSignal({ type, pair: asset, time, strategy: strategy || currentStrategy });
        }
        if (strategy) setCurrentStrategy(strategy);
        // CORREÇÃO DEFINITIVA: Ignorar valores do backend e forçar o cálculo exato do timeframe do botão no painel.
        setExpirationCountdown(timeframe * 60);
        
        setPendingSignalType(null);
        playSound(880, 0.3);
      }

      if (state === 'WIN') {
        playSound(1200, 0.2);
        setTimeout(() => playSound(1500, 0.3), 100);
      }

      if (state === 'LOSS') {
        playSound(200, 0.5);
      }
    });


    return () => {
      if (socketRef.current) {
        socketRef.current.disconnect();
      }
    };
  }, [isActive, customBridgeUrl]);

  // Countdown timers
  useEffect(() => {
    if (preAlertCountdown > 0) {
      const timer = setInterval(() => {
        setPreAlertCountdown(c => {
          if (c <= 1) {
            clearInterval(timer);
            return 0;
          }
          playSound(550, 0.05);
          return c - 1;
        });
      }, 1000);
      return () => clearInterval(timer);
    }
  }, [preAlertCountdown]);

  useEffect(() => {
    if (expirationCountdown > 0) {
      const timer = setInterval(() => {
        setExpirationCountdown(c => {
          if (c <= 1) {
            clearInterval(timer);
            return 0;
          }
          return c - 1;
        });
      }, 1000);
      return () => clearInterval(timer);
    }
  }, [expirationCountdown]);

  useEffect(() => {
    if (socketRef.current) {
      socketRef.current.emit('toggle_ai', { active: isActive });
    }
    if (!isActive) {
      setRobotState('IDLE');
      setExpirationCountdown(0);
      setPreAlertCountdown(0);
    }
  }, [isActive]);

  // Busca histórico do Supabase ao carregar e a cada 30s
  useEffect(() => {
    fetchHistory();
    const interval = setInterval(fetchHistory, 30000);
    return () => clearInterval(interval);
  }, []);
  const connectViaSsid = () => {
    if (socketRef.current && manualSsid) {
      setIsCapturing(true);
      socketRef.current.emit('set_ssid', { ssid: manualSsid, is_demo: true });
    }
  };


  return (
    <div className="flex flex-col h-screen max-h-screen bg-[#010409] font-sans selection:bg-lime-500/20">


      <div className="scanline" />
      <div className="vignette" />
      <div className="neural-flux">
        <div className="flux-node w-[400px] h-[400px] -top-20 -left-20" />
        <div className="flux-node w-[300px] h-[300px] -bottom-20 -right-20 [animation-delay:-5s]" />
        <div className="flux-node w-[250px] h-[250px] top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 [animation-delay:-10s]" />
      </div>
      <div className="cyber-grid" />

      {/* Header */}
      <header className="relative z-10 px-6 pt-8 pb-4 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 flex items-center justify-center bg-lime-500/20 rounded-lg border border-lime-500/30">
            <Cpu className="w-5 h-5 text-lime-400" />
          </div>
          <h1 className="text-lg font-black tracking-tighter text-white uppercase italic">
            Profit<span className="text-lime-400">Wave</span> <span className="text-[10px] text-slate-500 font-mono not-italic ml-1">IA.v4</span>
          </h1>
        </div>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-lime-400/10 border border-lime-400/20 rounded-lg hidden sm:flex">
             <div className="w-1.5 h-1.5 rounded-full bg-lime-400 animate-pulse shadow-[0_0_8px_rgba(163,230,53,0.8)]" />
             <span className="text-[8px] font-black text-lime-400 tracking-widest uppercase">High Precision</span>
          </div>

          <div className="flex items-center gap-3">
            {/* Bridge Status */}
            <div className="flex flex-col items-end">
              <div className="flex items-center gap-1.5">
                <div className={`w-1.5 h-1.5 rounded-full ${isBridgeConnected ? 'bg-lime-400 shadow-[0_0_8px_rgba(163,230,53,0.8)]' : 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]'}`} />
                <span className={`text-[8px] font-mono font-bold uppercase tracking-widest ${isBridgeConnected ? 'text-lime-400' : 'text-rose-400'}`}>
                  {isBridgeConnected ? 'Ponte ON' : 'Ponte OFF'}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className={`w-1.5 h-1.5 rounded-full ${isBrokerConnected ? 'bg-lime-400 shadow-[0_0_8px_rgba(163,230,53,0.8)]' : 'bg-slate-600'}`} />
                <span className={`text-[8px] font-mono font-bold uppercase tracking-widest ${isBrokerConnected ? 'text-lime-400' : 'text-slate-500'}`}>
                  {isBrokerConnected ? 'Quotex' : 'Desconectado'}
                </span>
              </div>
            </div>
            
            <button 
              onClick={() => setIsSettingsOpen(true)}
              className="p-2 hover:bg-white/5 rounded-lg transition-colors border border-transparent hover:border-white/10 group"
            >
              <Settings className="w-4 h-4 text-slate-500 group-hover:text-white transition-colors" />
            </button>
          </div>
        </div>
      </header>

      {/* Central Interactive Core */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 min-h-0">
        
        <div className="relative w-full max-w-sm aspect-square flex items-center justify-center">
          
          {/* Neural Rings */}
          <div className="absolute inset-0">
            <AnimatePresence>
               {robotState !== 'IDLE' && (
                 <>
                  <div key="ring1" className="pulse-ring inset-0 m-auto w-full h-full" />
                  <div key="ring2" className="pulse-ring inset-0 m-auto w-[80%] h-[80%] [animation-delay:1s]" />
                  <div key="ring3" className="pulse-ring inset-0 m-auto w-[60%] h-[60%] [animation-delay:2s]" />
                 </>
               )}
            </AnimatePresence>
          </div>

          {/* AI Core State Display (Clean Floating Interface) */}
          <div className="relative w-full max-w-[320px] aspect-square flex flex-col items-center justify-center">
            
            {/* Inner Particle Stream */}
            <div className="absolute inset-0 opacity-10 [mask-image:radial-gradient(circle,black,transparent_70%)]">
               <motion.div 
                 animate={{ rotate: 360 }}
                 transition={{ duration: 25, repeat: Infinity, ease: 'linear' }}
                 className="absolute inset-0 border-[30px] border-dotted border-lime-400 scale-150 opacity-20" 
               />
            </div>

            <AnimatePresence mode="wait">
              {robotState === 'IDLE' && (
                <motion.div 
                  key="idle"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 1.2 }}
                  className="flex flex-col items-center gap-6 px-8 text-center"
                >
                  <div className="relative group">
                    {/* Glowing Aura */}
                    <motion.div 
                      animate={{ 
                        scale: [1, 1.2, 1],
                        opacity: [0.1, 0.3, 0.1]
                      }}
                      transition={{ duration: 4, repeat: Infinity }}
                      className="absolute inset-0 bg-lime-500 rounded-full blur-3xl"
                    />
                    
                    {/* Orbiting Ring */}
                    <motion.div 
                      animate={{ rotate: 360 }}
                      transition={{ duration: 10, repeat: Infinity, ease: 'linear' }}
                      className="absolute -inset-4 border border-lime-500/20 rounded-full border-dashed"
                    />

                    <div className="relative w-24 h-24 rounded-full bg-slate-950/80 backdrop-blur-xl flex items-center justify-center border border-white/10 shadow-[0_0_30px_rgba(0,0,0,0.5)]">
                      <motion.div
                        animate={{ 
                          filter: ["drop-shadow(0 0 2px rgba(163,230,53,0.3))", "drop-shadow(0 0 8px rgba(163,230,53,0.6))", "drop-shadow(0 0 2px rgba(163,230,53,0.3))"] 
                        }}
                        transition={{ duration: 2, repeat: Infinity }}
                      >
                        <Brain className="w-12 h-12 text-lime-400" />
                      </motion.div>
                      
                      {/* Floating bits around the brain */}
                      <motion.div 
                        animate={{ rotate: -360 }}
                        transition={{ duration: 15, repeat: Infinity, ease: 'linear' }}
                        className="absolute inset-0"
                      >
                        <CircuitBoard className="absolute -top-1 -right-1 w-4 h-4 text-lime-400/30" />
                        <Zap className="absolute -bottom-1 -left-1 w-4 h-4 text-lime-400/30" />
                      </motion.div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <motion.h3 
                      animate={{ opacity: [0.5, 1, 0.5] }}
                      transition={{ duration: 3, repeat: Infinity }}
                      className="text-white font-black text-3xl tracking-tighter uppercase italic drop-shadow-[0_0_10px_rgba(163,230,53,0.3)]"
                    >
                      IA <span className="text-lime-400">DESLIGADA</span>
                    </motion.h3>
                    <div className="flex flex-col items-center">
                      <span className="text-slate-500 font-mono text-[10px] tracking-[0.3em] uppercase mb-1">Status do Sistema</span>
                      <p className="text-slate-400 text-xs italic font-medium tracking-wide">
                        AGUARDANDO COMANDO NEURAL...
                      </p>
                    </div>
                  </div>
                  
                  {/* Status Lights */}
                  {!isBridgeConnected && (
                    <motion.button 
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      onClick={() => setIsSettingsOpen(true)}
                      className="mt-4 px-4 py-2 bg-rose-500/10 border border-rose-500/20 rounded-lg text-rose-400 text-[10px] font-bold uppercase tracking-widest hover:bg-rose-500/20 transition-all flex items-center gap-2"
                    >
                      <LinkIcon className="w-3 h-3" /> Configurar Ponte (ngrok)
                    </motion.button>
                  )}
                  <div className="flex gap-1.5 mt-2">
                    {[1, 2, 3].map(i => (
                      <div key={i} className="w-1 h-1 rounded-full bg-slate-800" />
                    ))}
                  </div>
                </motion.div>
              )}

              {robotState === 'ANALYZING' && (
                <motion.div 
                  key="analyzing"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-col items-center gap-6"
                >
                  <motion.div 
                    animate={{ scale: [1, 1.1, 1], rotate: [0, 90, 180, 270, 360] }}
                    transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
                    className="w-20 h-20 rounded-full border-2 border-dashed border-lime-400/40 flex items-center justify-center"
                  >
                    <Radio className="w-8 h-8 text-lime-400" />
                  </motion.div>
                  <div className="text-center">
                    <div className="text-lime-400 font-black text-2xl tracking-tighter italic uppercase">
                      Próxima Análise {timeframe === 5 ? '[M5]' : '[M1]'}
                    </div>
                    <div className="text-5xl font-mono text-white tracking-widest mt-3 font-black bg-lime-400/10 px-6 py-2 rounded-xl border border-lime-400/20 shadow-[0_0_20px_rgba(163,230,53,0.15)]">
                      {formatTime(analysisCountdown)}
                    </div>
                    <div className="mt-4 text-[10px] text-slate-500 font-mono uppercase tracking-[0.3em] opacity-60">
                      Monitorando: {currentAsset.pair}
                    </div>
                  </div>
                </motion.div>
              )}

              {robotState === 'PRE_ALERT' && (
                <motion.div 
                  key="pre-alert"
                  initial={{ opacity: 0, scale: 0.5 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 2 }}
                  className="flex flex-col items-center gap-4 w-full"
                >
                  <div className="text-center">
                    <span className="text-slate-500 font-mono text-[10px] tracking-[0.3em] uppercase block mb-1">Confirmando Sinal</span>
                    <div className="flex flex-col items-center gap-1">
                      <div className="text-xl font-black text-lime-400 tracking-widest bg-lime-400/10 py-1 px-4 rounded-xl border border-lime-400/20">
                        {currentAsset.pair}
                      </div>
                      <div className="flex gap-2 items-center">
                        <div className={`text-[10px] font-black italic tracking-tighter uppercase px-3 py-0.5 rounded ${pendingSignalType === 'CALL' ? 'text-lime-400 bg-lime-400/10' : 'text-rose-500 bg-rose-500/10'}`}>
                          {pendingSignalType === 'CALL' ? 'PREPARA COMPRA' : 'PREPARA VENDA'}
                        </div>
                        {currentStrategy && (
                          <div className="bg-white/5 border border-white/10 text-white/60 text-[8px] px-2 py-0.5 rounded font-mono uppercase tracking-widest">
                            {currentStrategy}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="relative">
                    <div className="text-8xl font-black text-white italic tracking-tighter drop-shadow-[0_0_15px_rgba(163,230,53,0.6)]">
                      {formatTime(preAlertCountdown)}
                    </div>
                  </div>

                  <div className="flex flex-col items-center gap-2 w-full px-4">
                    <div className="grid grid-cols-2 gap-2 w-full">
                      <div className="bg-white/5 border border-white/10 rounded-lg p-2 flex flex-col items-center">
                        <span className="text-[7px] text-slate-500 font-mono uppercase tracking-widest mb-1">Entrada prevista</span>
                        <span className="text-xs font-bold text-white">
                          {new Date(Date.now() + preAlertCountdown * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <div className="bg-white/5 border border-white/10 rounded-lg p-2 flex flex-col items-center">
                        <span className="text-[7px] text-slate-500 font-mono uppercase tracking-widest mb-1">Assertividade</span>
                        <span className="text-xs font-bold text-lime-400">96.2%</span>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}

              {(robotState === 'WIN' || robotState === 'LOSS') && (
                <motion.div 
                  key="result"
                  initial={{ opacity: 0, scale: 0.8, y: 20 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 1.2 }}
                  className="flex flex-col items-center gap-2"
                >
                  <div className={`text-6xl font-black italic tracking-tighter drop-shadow-lg ${robotState === 'WIN' ? 'text-lime-400' : 'text-rose-500'}`}>
                    {robotState === 'WIN' ? 'VÍTÓRIA!' : 'DERROTA'}
                  </div>
                  <div className="text-white/40 font-mono text-xs uppercase tracking-[0.3em]">
                    Resultado do Sinal
                  </div>
                  
                  {robotState === 'WIN' && (
                    <motion.div 
                      animate={{ opacity: [0, 1, 0] }}
                      transition={{ duration: 1, repeat: Infinity }}
                      className="absolute inset-0 bg-lime-400/10 blur-[100px] -z-10"
                    />
                  )}
                </motion.div>
              )}

              {robotState === 'CONFIRMED' && (
                <motion.div 
                  key="confirmed"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="flex flex-col items-center w-full px-6"
                >
                  <div className={`text-5xl font-black italic tracking-tighter mb-1 flex items-center gap-3 drop-shadow-[0_0_15px_rgba(0,0,0,0.5)] ${lastSignal?.type === 'CALL' ? 'text-lime-400' : 'text-rose-500'}`}>
                    {lastSignal?.type === 'CALL' ? <TrendingUp className="w-10 h-10" /> : <TrendingDown className="w-10 h-10" />}
                    {lastSignal?.type === 'CALL' ? 'COMPRA' : 'VENDA'}
                  </div>
                  
                  <div className="flex flex-col items-center gap-2 mb-3">
                    <span className="bg-lime-400/20 text-lime-400 text-[10px] px-3 py-1 rounded-md font-black tracking-widest border border-lime-400/30 uppercase">
                      Assertividade da IA: 96.2%
                    </span>
                    {lastSignal?.strategy && (
                      <span className="text-white/40 text-[8px] font-mono uppercase tracking-[0.2em] bg-white/5 px-2 py-0.5 rounded border border-white/5">
                        Estratégia: {lastSignal.strategy}
                      </span>
                    )}
                  </div>
                  
                  <div className="w-full space-y-3">
                    <div className="grid grid-cols-2 gap-2">
                       <div className="bg-white/5 border border-white/10 rounded-lg p-2 flex flex-col items-center">
                          <span className="text-[8px] text-slate-500 font-mono uppercase tracking-widest mb-1">Horário</span>
                          <span className="text-sm font-bold text-white">{lastSignal?.time}</span>
                       </div>
                       <div className="bg-white/5 border border-white/10 rounded-xl p-2 flex flex-col items-center">
                          <span className="text-[8px] text-slate-500 font-mono uppercase tracking-widest mb-1">Expiração</span>
                          <span className="text-sm font-bold text-white">{timeframe} MIN</span>
                       </div>
                    </div>

                    <div className="bg-lime-400/10 border border-lime-400/30 rounded-xl p-3 flex flex-col items-center relative overflow-hidden">
                       <motion.div 
                         initial={{ width: '100%' }}
                         animate={{ width: '0%' }}
                         transition={{ duration: expirationCountdown > 65 ? 300 : 60, ease: 'linear' }}
                         className={`absolute bottom-0 left-0 h-1 shadow-[0_0_10px_rgba(163,230,53,0.8)] ${lastSignal?.type === 'CALL' ? 'bg-lime-400' : 'bg-rose-500'}`} 
                       />
                       <span className="text-[9px] text-lime-500 font-mono uppercase tracking-[0.2em] mb-1 font-bold">Tempo de Entrada</span>
                       <span className="text-2xl font-black text-white italic tracking-tighter">
                         {formatTime(expirationCountdown)}
                       </span>
                    </div>

                    <div className="text-center">
                       <span className="text-[9px] text-slate-500 font-mono uppercase tracking-[0.3em] opacity-50 block mb-1">Ativo Detectado</span>
                       <span className="text-xl font-black text-white tracking-widest bg-white/5 py-1 px-4 rounded-xl border border-white/5 inline-block">
                         {lastSignal?.pair}
                       </span>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </main>

      {/* Bottom Controls */}
      <footer className="relative z-10 p-8 pt-0">
        <div className="max-w-md mx-auto">
          {/* Timeframe Selector */}
          <div className="flex items-center justify-center gap-4 mb-6">
            <span className="text-[10px] text-slate-500 font-mono uppercase tracking-[0.2em]">Tempo de Vela:</span>
            <div className="flex bg-white/5 p-1 rounded-xl border border-white/10">
              {[1, 5].map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    setTimeframe(m as 1 | 5);
                    playSound(440 + m * 40, 0.1);
                  }}
                  disabled={isActive}
                  className={`px-6 py-2 rounded-lg text-xs font-black transition-all ${
                    timeframe === m 
                      ? 'bg-lime-400 text-black shadow-lg shadow-lime-400/20' 
                      : 'text-white/40 hover:text-white'
                  } ${isActive ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  M{m}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => {
              const newState = !isActive;
              setIsActive(newState);
              socketRef.current?.emit('toggle_ai', { active: newState, timeframe });
              playSound(newState ? 880 : 220, 0.2);
            }}
            className={`w-full group relative overflow-hidden flex items-center justify-center gap-4 py-6 rounded-3xl font-black text-lg tracking-tight uppercase shadow-2xl transition-all active:scale-95 ${
              isActive 
              ? 'bg-rose-500 text-white shadow-rose-500/40 ring-4 ring-rose-500/20' 
              : 'bg-lime-400 text-black shadow-lime-500/40 ring-4 ring-lime-500/20'
            }`}
          >
            <div className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity" />
            <motion.div
              animate={isActive ? { rotate: 360 } : { scale: 1 }}
              transition={{ duration: 4, repeat: Infinity, ease: 'linear' }}
            >
              {isActive ? <Square className="w-6 h-6 fill-white" /> : <Play className="w-6 h-6 fill-black" />}
            </motion.div>
            {isActive ? 'PARAR IA' : 'ATIVAR IA'}
          </button>

          {/* SSID Status Message */}
          {ssidMessage && ssidStatus !== 'IDLE' && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`mt-3 px-4 py-2.5 rounded-xl text-xs font-bold text-center border ${
                ssidStatus === 'CONNECTED' ? 'bg-lime-400/10 border-lime-400/30 text-lime-400' :
                ssidStatus === 'ERROR' ? 'bg-rose-500/10 border-rose-500/30 text-rose-400' :
                'bg-amber-500/10 border-amber-500/30 text-amber-400'
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                {ssidStatus === 'CONNECTED' && <CheckCircle className="w-3.5 h-3.5" />}
                {ssidStatus === 'ERROR' && <AlertTriangle className="w-3.5 h-3.5" />}
                {isCapturing && ssidStatus !== 'CONNECTED' && ssidStatus !== 'ERROR' && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                )}
                {ssidMessage}
              </div>
            </motion.div>
          )}

          <div className="grid grid-cols-2 gap-3 mt-4">
            {/* Conectar Corretora Button */}
            <button
              onClick={() => {
                if (!isBridgeConnected) {
                  setSsidStatus('ERROR');
                  const msg = serverType === 'CLOUD' 
                    ? 'Ponte Nuvem desconectada. Verifique o link do Render nas configurações.'
                    : 'Inicie a ponte primeiro (python quotex_bridge.py)';
                  setSsidMessage(msg);
                  return;
                }
                if (isCapturing) return;

                if (serverType === 'CLOUD') {
                  setIsSettingsOpen(true);
                  return;
                }

                setSsidStatus('LAUNCHING');
                setSsidMessage('Abrindo navegador...');
                setIsCapturing(true);
                socketRef.current?.emit('capture_ssid', {});
                playSound(660, 0.15);
              }}
              disabled={isCapturing || isBrokerConnected}
              className={`flex items-center justify-center gap-2 py-3 rounded-2xl text-[11px] font-black uppercase tracking-tighter transition-all active:scale-95 ${
                isBrokerConnected 
                  ? 'bg-lime-400/10 border border-lime-400/30 text-lime-400 cursor-default'
                  : isCapturing
                    ? 'bg-amber-500/10 border border-amber-500/30 text-amber-400 cursor-wait'
                    : serverType === 'CLOUD'
                      ? 'bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20'
                      : 'bg-white/5 border border-white/10 text-white hover:bg-lime-400/10 hover:border-lime-400/30 hover:text-lime-400'
              }`}
            >
              {isBrokerConnected ? (
                <><CheckCircle className="w-3.5 h-3.5" /> Conectado</>
              ) : isCapturing ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Capturando...</>
              ) : serverType === 'CLOUD' ? (
                <><Settings className="w-3.5 h-3.5 text-cyan-400" /> Configurar SSID (Nuvem)</>
              ) : (
                <><Globe className="w-3.5 h-3.5 text-lime-400" /> Conectar Quotex</>
              )}
            </button>
            {/* WhatsApp Support */}
            <a 
              href="https://wa.me/5569996078041" 
              target="_blank" 
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 py-3 bg-white/5 border border-white/10 rounded-2xl text-[11px] font-black text-white uppercase tracking-tighter hover:bg-white/10 transition-colors"
            >
              <MessageSquare className="w-3.5 h-3.5 text-lime-400" />
              Suporte WhatsApp
            </a>
          </div>

          <div className="mt-6 text-center">
            <p className="text-[10px] text-slate-800 font-mono tracking-widest flex items-center justify-center gap-2 font-bold uppercase">
              <Shield className="w-3 h-3" /> IA.v4 - Núcleo Ativo
            </p>
          </div>
        </div>
      </footer>

      {/* Connection Settings Modal */}
      <AnimatePresence>
        {isSettingsOpen && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-6 sm:p-0">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsSettingsOpen(false)}
              className="absolute inset-0 bg-black/80 backdrop-blur-sm"
            />
            
            <motion.div 
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              className="relative w-full max-w-sm bg-[#0d1117] border border-white/10 rounded-3xl overflow-hidden shadow-2xl"
            >
              <div className="p-6 border-b border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-lime-400/10 flex items-center justify-center">
                    <Settings className="w-4 h-4 text-lime-400" />
                  </div>
                  <h2 className="text-white font-black text-sm uppercase tracking-widest">Configurações</h2>
                </div>
                <button 
                  onClick={() => setIsSettingsOpen(false)}
                  className="p-2 hover:bg-white/5 rounded-lg transition-colors"
                >
                  <X className="w-4 h-4 text-slate-500" />
                </button>
              </div>
              
              <div className="p-6 space-y-6">
                <div className="space-y-3">
                  <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block">URL da Ponte (ngrok ou Local)</label>
                  <div className="relative">
                    <input 
                      type="text" 
                      value={customBridgeUrl}
                      onChange={(e) => {
                        const val = e.target.value;
                        setCustomBridgeUrl(val);
                        localStorage.setItem('profitwave_bridge_url', val);
                      }}
                      placeholder="Ex: https://xxxx-xxx.ngrok-free.app"
                      className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white font-mono placeholder:text-slate-700 focus:outline-none focus:border-lime-400/50 transition-colors"
                    />
                    {customBridgeUrl && (
                      <button 
                        onClick={() => {
                          setCustomBridgeUrl('');
                          localStorage.removeItem('profitwave_bridge_url');
                        }}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-rose-400 hover:text-rose-300 transition-colors"
                      >
                        LIMPAR
                      </button>
                    )}
                  </div>
                  <p className="text-[9px] text-slate-600 leading-relaxed">
                    Deixe vazio para usar o padrão (localhost:5001). <br/>
                    Se estiver no Vercel, cole aqui a URL do seu ngrok.
                  </p>
                </div>

                <div className="space-y-3">
                  <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest block">Conexão via SSID (Nuvem)</label>
                  <div className="relative">
                    <textarea 
                      value={manualSsid}
                      onChange={(e) => {
                        const val = e.target.value;
                        setManualSsid(val);
                        localStorage.setItem('profitwave_manual_ssid', val);
                      }}
                      placeholder='Cole aqui o código SSID (começa com 42["authorization"...)'
                      className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-[10px] text-white font-mono placeholder:text-slate-700 focus:outline-none focus:border-cyan-400/50 transition-colors h-24 resize-none"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button 
                      onClick={connectViaSsid}
                      disabled={!manualSsid || !isBridgeConnected}
                      className="flex-1 py-3 bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 font-black text-[10px] uppercase tracking-widest rounded-xl hover:bg-cyan-500/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    >
                      Conectar via SSID
                    </button>
                    <a 
                      href="/CAPTURE_SSID.txt" 
                      target="_blank"
                      className="px-4 py-3 bg-white/5 border border-white/10 text-slate-400 font-black text-[10px] uppercase tracking-widest rounded-xl hover:bg-white/10 transition-all flex items-center justify-center"
                    >
                      Como Pegar?
                    </a>
                  </div>
                  <p className="text-[9px] text-slate-600 leading-relaxed">
                    Use esta opção se o robô estiver hospedado no Render/Railway.
                  </p>
                </div>

                <div className="bg-lime-400/5 border border-lime-400/10 rounded-xl p-4">
                  <h4 className="text-[10px] font-black text-lime-400 uppercase tracking-widest mb-2">Instruções de Deploy:</h4>
                  <ol className="text-[9px] text-slate-400 space-y-2 list-decimal ml-3">
                    <li>Suba o código atualizado no seu <code className="text-white font-bold">GitHub</code>.</li>
                    <li>No <code className="text-lime-400">Render.com</code>, crie um "New Web Service".</li>
                    <li>Conecte seu repositório e use o <code className="text-white font-bold">bridge_cloud.py</code>.</li>
                    <li>Copie a URL do Render e cole no campo "URL da Ponte" acima.</li>
                  </ol>
                </div>
              </div>
              
              <div className="p-6 bg-white/3">
                <button 
                  onClick={() => setIsSettingsOpen(false)}
                  className="w-full py-3 bg-lime-400 text-black font-black text-xs uppercase tracking-widest rounded-xl hover:scale-[1.02] transition-all"
                >
                  Salvar e Fechar
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ===== HISTÓRICO SUPABASE ===== */}
      <div className="relative z-10 px-4 pb-6">
        <div className="bg-white/3 border border-white/8 rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/8">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-lime-400" />
              <span className="text-[11px] font-black text-white uppercase tracking-widest">Histórico</span>
              <span className="text-[9px] bg-lime-500/20 text-lime-400 px-2 py-0.5 rounded-full font-mono">Supabase Live</span>
            </div>
            <button
              onClick={fetchHistory}
              className="text-[9px] text-slate-500 hover:text-lime-400 font-mono transition-colors uppercase tracking-widest"
            >↻ Atualizar</button>
          </div>

          {tradeHistory.length === 0 ? (
            <div className="py-8 text-center text-slate-600 text-[11px] font-mono">
              Nenhum sinal registrado ainda.
            </div>
          ) : (
            <div className="divide-y divide-white/5">
              {tradeHistory.map((trade) => {
                const d = new Date(trade.created_at);
                const time = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
                const date = d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                return (
                  <div key={trade.id} className="flex items-center justify-between px-4 py-2.5">
                    <div className="flex items-center gap-3">
                      <div className={`w-1.5 h-6 rounded-full ${
                        trade.result === 'WIN' ? 'bg-lime-400' :
                        trade.result === 'LOSS' ? 'bg-red-500' : 'bg-yellow-400/60'
                      }`} />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] font-bold text-white">{trade.asset}</span>
                          <span className={`text-[9px] font-black px-1.5 py-0.5 rounded ${
                            trade.signal_type === 'CALL'
                              ? 'bg-lime-500/20 text-lime-400'
                              : 'bg-red-500/20 text-red-400'
                          }`}>{trade.signal_type}</span>
                          <span className="text-[9px] text-slate-500 font-mono">M{trade.timeframe}</span>
                        </div>
                        <div className="text-[9px] text-slate-500 font-mono">{trade.strategy}</div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-[11px] font-black ${
                        trade.result === 'WIN' ? 'text-lime-400' :
                        trade.result === 'LOSS' ? 'text-red-400' : 'text-yellow-400'
                      }`}>
                        {trade.result === 'WIN' ? '✓ WIN' : trade.result === 'LOSS' ? '✗ LOSS' : '⏳'}
                      </div>
                      <div className="text-[9px] text-slate-600 font-mono">{date} {time}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Floaters for visuals */}
      <FloatingElements />
    </div>
  );
}

function FloatingElements() {
  return (
    <div className="fixed inset-0 pointer-events-none">
      {[...Array(30)].map((_, i) => (
        <motion.div
          key={i}
          initial={{ 
            y: '110vh', 
            x: `${Math.random() * 100}%`, 
            scale: Math.random() * 0.5 + 0.2,
            opacity: Math.random() * 0.3 + 0.1
          }}
          animate={{ 
            y: '-10vh', 
            x: [`${Math.random() * 100}%`, `${Math.random() * 100}%`],
            rotate: 360 
          }}
          transition={{ 
            duration: 20 + Math.random() * 20, 
            repeat: Infinity, 
            ease: 'linear', 
            delay: Math.random() * 10 
          }}
          className="absolute"
        >
          {i % 2 === 0 ? (
            <div className="w-1.5 h-1.5 bg-lime-400 rounded-sm shadow-[0_0_8px_rgba(163,230,53,0.8)]" />
          ) : (
            <div className="w-1 h-1 bg-white/40 rounded-full" />
          )}
        </motion.div>
      ))}
    </div>
  );
}



import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Linking, Platform, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import * as Location from 'expo-location';
import * as Speech from 'expo-speech';
import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || (Platform.OS === 'android' ? 'http://10.0.2.2:8765' : 'http://localhost:8765');
const HANOI = { lat: 21.0285, lon: 105.8542 };
const SAMPLE = [
  { name: 'Petrolimex Trần Hưng Đạo', lat: 21.0173, lon: 105.8536, address: 'Trần Hưng Đạo, Hoàn Kiếm', travelMinutes: 5, distanceMeters: 1600 },
  { name: 'PVOIL Láng Hạ', lat: 21.0148, lon: 105.8179, address: 'Láng Hạ, Đống Đa', travelMinutes: 8, distanceMeters: 2700 },
  { name: 'Petrolimex Nguyễn Trãi', lat: 20.9986, lon: 105.8132, address: 'Nguyễn Trãi, Thanh Xuân', travelMinutes: 11, distanceMeters: 3900 },
  { name: 'PVOIL Kim Mã', lat: 21.0309, lon: 105.8217, address: 'Kim Mã, Ba Đình', travelMinutes: 7, distanceMeters: 2300 },
  { name: 'Petrolimex Minh Khai', lat: 20.999, lon: 105.867, address: 'Minh Khai, Hai Bà Trưng', travelMinutes: 10, distanceMeters: 3200 },
];
const PRESETS = [
  { label: 'Hoàn Kiếm', coords: HANOI },
  { label: 'Cầu Giấy', coords: { lat: 21.0307, lon: 105.7906 } },
  { label: 'Đống Đa', coords: { lat: 21.018, lon: 105.829 } },
];

export default function App() {
  const [origin, setOrigin] = useState(HANOI);
  const [place, setPlace] = useState('Hoàn Kiếm, Hà Nội');
  const [range, setRange] = useState('15');
  const [stations, setStations] = useState(SAMPLE);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState('DEMO DATA');
  const [notice, setNotice] = useState('Sample stations shown. Choose an area or use your location, then search.');
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [voiceError, setVoiceError] = useState('');
  const remaining = Math.max(0, Math.min(300, Number(range) || 0));
  const ranked = useMemo(() => stations.map(station => {
    const distanceKm = Number.isFinite(station.distanceMeters) ? station.distanceMeters / 1000 : null;
    const minutes = Number.isFinite(station.travelMinutes) ? Math.ceil(station.travelMinutes) : null;
    return { ...station, distanceKm, minutes, reachable: distanceKm !== null && distanceKm <= remaining * 0.8 };
  }).sort((a, b) => (a.minutes ?? Infinity) - (b.minutes ?? Infinity)), [stations, remaining]);
  const best = ranked.find(station => station.reachable) || ranked[0];

  useSpeechRecognitionEvent('start', () => { setListening(true); setVoiceError(''); });
  useSpeechRecognitionEvent('end', () => setListening(false));
  useSpeechRecognitionEvent('result', event => {
    const transcript = event.results?.[0]?.transcript?.trim();
    if (transcript) {
      setQuestion(transcript);
      sendQuestion(transcript);
    }
  });
  useSpeechRecognitionEvent('error', event => {
    setListening(false);
    setVoiceError(event.message || 'Không nhận diện được giọng nói. Hãy thử lại hoặc nhập câu hỏi.');
  });

  function answerFromStations(text) {
    if (!ranked.length) return 'Chưa có danh sách trạm để so sánh. Hãy tìm trạm gần bạn trước.';
    const normalized = text.toLocaleLowerCase('vi').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');
    if (/hang cho|doi|cho lau|dong/.test(normalized)) return 'Ứng dụng chưa có dữ liệu trực tiếp về hàng chờ tại cây xăng. Thời gian chờ chưa rõ.';
    if (/gan nhat|khoang cach|xa nhat/.test(normalized)) {
      const nearest = [...ranked].sort((a, b) => (a.distanceKm ?? Infinity) - (b.distanceKm ?? Infinity))[0];
      return `${nearest.name} gần nhất theo khoảng cách ước tính${nearest.distanceKm === null ? '' : `, khoảng ${nearest.distanceKm.toFixed(1)} km`}.`;
    }
    if (/het xang|khong du xang|xe khong toi|du xang/.test(normalized) && best) return `${best.name} là lựa chọn gần nhất trong danh sách theo ước tính hiện tại. Quãng đường không đảm bảo xe tới được; hãy đi thận trọng.`;
    const fastest = ranked.find(station => station.minutes !== null);
    return fastest ? `${fastest.name} có thời gian di chuyển ước tính ngắn nhất trong danh sách, khoảng ${fastest.minutes} phút. Đây không phải chỉ dẫn an toàn hay bảo đảm tới nơi.` : 'Chưa có thời gian di chuyển cho các trạm này.';
  }

  async function sendQuestion(text = question) {
    const prompt = text.trim();
    if (!prompt || assistantBusy) return;
    setQuestion('');
    setVoiceError('');
    setMessages(current => [...current, { role: 'user', text: prompt }]);
    setAssistantBusy(true);
    let reply;
    try {
      const options = ranked.slice(0, 3).map(({ name, address, travelMinutes, distanceMeters, queueCount, waitMinutes, totalMinutes, crowd }) => ({ name, address, travelMinutes, distanceMeters, queueCount, waitMinutes, totalMinutes, crowd }));
      const response = await fetch(`${API_BASE_URL}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: prompt, stations: options }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `Assistant unavailable (${response.status})`);
      reply = data.answer;
    } catch {
      reply = answerFromStations(prompt);
    } finally {
      setAssistantBusy(false);
    }
    setMessages(current => [...current, { role: 'assistant', text: reply }]);
    if (speakReplies) Speech.speak(reply, { language: 'vi-VN', rate: 0.92 });
  }

  async function startVoiceInput() {
    try {
      if (!ExpoSpeechRecognitionModule.isRecognitionAvailable()) {
        setVoiceError('Thiết bị chưa có dịch vụ nhận diện giọng nói. Bạn có thể nhập câu hỏi.');
        return;
      }
      const permission = await ExpoSpeechRecognitionModule.requestPermissionsAsync();
      if (!permission.granted) {
        setVoiceError('Cần quyền micro và nhận diện giọng nói để dùng điều khiển giọng nói.');
        return;
      }
      ExpoSpeechRecognitionModule.start({ lang: 'vi-VN', interimResults: false, continuous: false });
    } catch (error) {
      setVoiceError(error.message || 'Không thể bắt đầu nhận diện giọng nói.');
    }
  }

  function choosePreset(preset) {
    setPlace(`${preset.label}, Hà Nội`);
    setOrigin(preset.coords);
    setNotice('Sample stations shown. Search to refresh nearby results.');
  }

  async function useCurrentLocation() {
    setBusy(true);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== 'granted') throw new Error('Location permission was not granted. Choose a Hanoi area instead.');
      const location = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const coords = { lat: location.coords.latitude, lon: location.coords.longitude };
      setOrigin(coords);
      setPlace('Current location');
      setNotice('Using your current location. Search for nearby stations.');
    } catch (error) {
      Alert.alert('Could not get location', error.message || 'Please choose a Hanoi area.');
    } finally {
      setBusy(false);
    }
  }

  async function search() {
    setBusy(true);
    setNotice('Searching nearby stations…');
    try {
      const response = await fetch(`${API_BASE_URL}/api/stations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(origin) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `Station search failed (${response.status})`);
      const found = (data.stations || []).map(station => ({ ...station, source: station.travelSource || 'Google Maps' }));
      if (!found.length) throw new Error('No fuel stations were returned for this area.');
      setStations(found);
      setSource('GOOGLE MAPS');
      setNotice(`${found.length} nearby stations · travel times from Google Routes. Queue information may be unavailable.`);
      setSource('GOOGLE MAPS');
    } catch (error) {
      setStations(SAMPLE);
      setSource('DEMO DATA');
      setNotice(`${error.message} Showing sample Hanoi stations instead.`);
    } finally {
      setBusy(false);
    }
  }

  function openMaps(station) {
    const url = `https://www.google.com/maps/dir/?api=1&destination=${station.lat},${station.lon}&travelmode=two-wheeler`;
    Linking.openURL(url).catch(() => Alert.alert('Unable to open maps', 'Please open Google Maps and search for this station.'));
  }

  return <SafeAreaView style={styles.safe}>
    <StatusBar barStyle="dark-content" backgroundColor="#f4f6f0" />
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <View style={styles.header}>
        <View style={styles.logo}><Text style={styles.logoText}>⛽</Text></View>
        <View style={styles.titleBlock}><Text style={styles.eyebrow}>HÀ NỘI · TÌM TRẠM XĂNG</Text><Text style={styles.title}>Fuel Finder</Text></View>
        <View style={styles.pill}><View style={[styles.dot, source === 'OpenStreetMap' && styles.dotLive]} /><Text style={styles.pillText}>{source}</Text></View>
      </View>
      <Text style={styles.subtitle}>Tìm trạm gần bạn phù hợp với quãng đường xăng còn lại.</Text>

      <View style={styles.card}>
        <Text style={styles.label}>ĐIỂM XUẤT PHÁT</Text>
        <View style={styles.input}><Text style={styles.placeText}>{place}</Text></View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          {PRESETS.map(preset => <TouchableOpacity key={preset.label} style={[styles.chip, place.startsWith(preset.label) && styles.chipSelected]} onPress={() => choosePreset(preset)}><Text style={[styles.chipText, place.startsWith(preset.label) && styles.chipTextSelected]}>{preset.label}</Text></TouchableOpacity>)}
          <TouchableOpacity style={styles.locationChip} onPress={useCurrentLocation} disabled={busy}><Text style={styles.locationText}>◎ Vị trí hiện tại</Text></TouchableOpacity>
        </ScrollView>
        <Text style={styles.helper}>Có thể chọn nhanh khu vực Hà Nội hoặc lấy vị trí thiết bị.</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>ƯỚC TÍNH QUÃNG ĐƯỜNG CÒN LẠI</Text>
        <View style={styles.rangeRow}><TextInput value={range} onChangeText={setRange} keyboardType="numeric" style={styles.rangeInput} accessibilityLabel="Quãng đường còn lại tính bằng kilomet" /><Text style={styles.unit}>km</Text><Text style={styles.caution}>Hãy nhập ước tính thận trọng</Text></View>
        <View style={styles.track}><View style={[styles.fill, { width: `${Math.min(100, remaining / 50 * 100)}%` }]} /></View>
        <Text style={styles.helper}>Đánh dấu “có thể tới” với dự phòng 20% và khoảng cách đường ước lượng.</Text>
      </View>

      <TouchableOpacity style={[styles.primary, busy && styles.primaryBusy]} onPress={search} disabled={busy} accessibilityRole="button">
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>⌕   Tìm cây xăng gần đây</Text>}
      </TouchableOpacity>
      <Text style={styles.notice} accessibilityLiveRegion="polite">{notice}</Text>

      {best && <>
        <View style={styles.sectionHeader}><Text style={styles.sectionTitle}>Gợi ý phù hợp nhất</Text><Text style={styles.count}>{ranked.length} trạm</Text></View>
        <View style={styles.bestCard}>
          <View style={styles.bestHead}><Text style={styles.bestLabel}>LỰA CHỌN THEO ƯỚC TÍNH</Text><Text style={[styles.status, best.reachable ? styles.statusOk : styles.statusWarn]}>{best.reachable ? 'Trong tầm dự phòng' : 'Chưa chắc đủ xăng'}</Text></View>
          <Text style={styles.bestName}>{best.name}</Text><Text style={styles.bestAddress}>{best.address || 'Chưa có địa chỉ'}</Text>
          <View style={styles.metrics}><Metric label="KHOẢNG CÁCH*" value={`~${best.distanceKm === null ? '—' : best.distanceKm.toFixed(1)} km`} /><Metric label="THỜI GIAN*" value={`~${best.minutes === null ? '—' : best.minutes + ' phút'}`} /><Metric label="DỰ PHÒNG*" value={`${best.distanceKm === null ? '—' : Math.max(0, remaining - best.distanceKm).toFixed(1) + ' km'}`} /></View>
          <TouchableOpacity style={styles.navigation} onPress={() => openMaps(best)}><Text style={styles.navigationText}>Mở chỉ đường ↗</Text></TouchableOpacity>
        </View>
      </>}

      <View style={styles.listHeader}><Text style={styles.sectionTitle}>Các trạm gần đây</Text><Text style={styles.sort}>XẾP THEO THỜI GIAN ƯỚC TÍNH</Text></View>
      {ranked.map((station, index) => <TouchableOpacity key={`${station.name}-${station.lat}-${index}`} style={styles.station} onPress={() => openMaps(station)} accessibilityRole="button" accessibilityLabel={`${station.name}, khoảng ${station.minutes} phút. Mở chỉ đường`}>
        <View style={styles.marker}><Text style={styles.markerText}>{index === 0 ? '★' : '⛽'}</Text></View>
        <View style={styles.stationDetails}><Text style={styles.stationName} numberOfLines={1}>{station.name}</Text><Text style={styles.stationAddress} numberOfLines={1}>{station.address}</Text><Text style={styles.stationMeta}>{station.source || source} · khoảng {station.distanceKm === null ? '—' : station.distanceKm.toFixed(1)} km</Text></View>
        <View style={styles.stationTime}><Text style={styles.time}>{station.minutes === null ? 'Chưa rõ' : station.minutes + ' phút'}</Text><Text style={[styles.reach, station.reachable ? styles.reachOk : styles.reachWarn]}>{station.reachable ? 'Có thể tới*' : 'Cần kiểm tra*'}</Text></View>
      </TouchableOpacity>)}
      <View style={styles.assistantCard}>
        <View style={styles.assistantHeader}><View><Text style={styles.assistantTitle}>Trợ lý Fuel Finder</Text><Text style={styles.assistantHint}>Hỏi về trạm gần nhất hoặc thời gian đi</Text></View><TouchableOpacity style={[styles.ttsToggle, speakReplies && styles.ttsToggleOn]} onPress={() => setSpeakReplies(value => !value)} accessibilityRole="switch" accessibilityState={{ checked: speakReplies }}><Text style={styles.ttsText}>{speakReplies ? '🔊 Đọc câu trả lời' : '🔇 Tắt đọc'}</Text></TouchableOpacity></View>
        <View style={styles.prompts}>{['Trạm nào gần nhất?', 'Tôi có kịp tới không?', 'Có đông không?'].map(prompt => <TouchableOpacity key={prompt} style={styles.promptChip} onPress={() => sendQuestion(prompt)} disabled={assistantBusy}><Text style={styles.promptText}>{prompt}</Text></TouchableOpacity>)}</View>
        {messages.map((message, index) => <View key={`${index}-${message.role}`} style={[styles.message, message.role === 'user' ? styles.userMessage : styles.assistantMessage]}><Text style={[styles.messageText, message.role === 'user' && styles.userMessageText]}>{message.text}</Text>{message.role === 'assistant' && <TouchableOpacity onPress={() => Speech.speak(message.text, { language: 'vi-VN', rate: 0.92 })} accessibilityLabel="Đọc lại câu trả lời"><Text style={styles.speakAgain}>▶ Nghe lại</Text></TouchableOpacity>}</View>)}
        {assistantBusy && <View style={styles.thinking}><ActivityIndicator size="small" color="#245b42" /><Text style={styles.assistantHint}>Đang tìm câu trả lời…</Text></View>}
        {!!voiceError && <Text style={styles.voiceError} accessibilityLiveRegion="polite">{voiceError}</Text>}
        <View style={styles.composer}><TextInput value={question} onChangeText={setQuestion} placeholder="Nhập câu hỏi…" style={styles.questionInput} returnKeyType="send" onSubmitEditing={() => sendQuestion()} accessibilityLabel="Câu hỏi cho trợ lý" /><TouchableOpacity style={[styles.micButton, listening && styles.micActive]} onPress={listening ? () => ExpoSpeechRecognitionModule.stop() : startVoiceInput} accessibilityRole="button" accessibilityLabel={listening ? 'Dừng ghi âm' : 'Hỏi bằng giọng nói'}><Text style={styles.micText}>{listening ? '■' : '🎙'}</Text></TouchableOpacity><TouchableOpacity style={styles.sendButton} onPress={() => sendQuestion()} disabled={assistantBusy || !question.trim()} accessibilityRole="button" accessibilityLabel="Gửi câu hỏi"><Text style={styles.sendText}>Gửi</Text></TouchableOpacity></View>
        <Text style={styles.assistantFootnote}>Nhận diện giọng nói dùng dịch vụ trên thiết bị. Câu hỏi được gửi tới máy chủ nếu có trợ lý cấu hình; nếu không, ứng dụng trả lời dựa trên danh sách hiện có.</Text>
      </View>
      <Text style={styles.disclaimer}>Thời gian đi do Google Routes ước tính và có thể thay đổi theo giao thông; không đảm bảo xe tới được. Quãng đường nhiên liệu còn lại cũng là ước tính của bạn, không phải bảo đảm. Hàng chờ tại trạm không được Google cung cấp. Hãy dừng xe an toàn trước khi thao tác.</Text>
    </ScrollView>
  </SafeAreaView>;
}

function Metric({ label, value }) {
  return <View style={styles.metric}><Text style={styles.metricLabel}>{label}</Text><Text style={styles.metricValue}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#f4f6f0' }, page: { padding: 18, paddingBottom: 42, maxWidth: 640, width: '100%', alignSelf: 'center' },
  header: { flexDirection: 'row', alignItems: 'center', gap: 11, marginTop: 8 }, logo: { width: 46, height: 46, borderRadius: 15, backgroundColor: '#dfeade', alignItems: 'center', justifyContent: 'center' }, logoText: { fontSize: 23 }, titleBlock: { flex: 1 }, eyebrow: { fontSize: 9, fontWeight: '800', letterSpacing: 1.2, color: '#287750' }, title: { fontSize: 24, fontWeight: '800', color: '#172d25' }, pill: { flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: 14, backgroundColor: '#fff', paddingHorizontal: 9, paddingVertical: 7, maxWidth: 120 }, dot: { width: 7, height: 7, borderRadius: 5, backgroundColor: '#dda83b' }, dotLive: { backgroundColor: '#20a56b' }, pillText: { fontSize: 9, fontWeight: '700', color: '#53655b' },
  assistantCard: { backgroundColor: '#fff', borderRadius: 17, padding: 15, marginTop: 18, borderWidth: 1, borderColor: '#e2e9e1' }, assistantHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 }, assistantTitle: { fontSize: 15, fontWeight: '800', color: '#20382d' }, assistantHint: { fontSize: 10, color: '#718077', marginTop: 3 }, ttsToggle: { borderRadius: 14, paddingHorizontal: 9, paddingVertical: 7, backgroundColor: '#f1f4f1' }, ttsToggleOn: { backgroundColor: '#e3f2e8' }, ttsText: { fontSize: 9, fontWeight: '700', color: '#245b42' }, prompts: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 12 }, promptChip: { borderRadius: 16, paddingHorizontal: 9, paddingVertical: 7, backgroundColor: '#edf4ee' }, promptText: { fontSize: 9, color: '#245b42', fontWeight: '600' }, message: { marginTop: 9, borderRadius: 12, padding: 10, maxWidth: '92%' }, userMessage: { alignSelf: 'flex-end', backgroundColor: '#245b42' }, assistantMessage: { alignSelf: 'flex-start', backgroundColor: '#f1f5ef' }, messageText: { fontSize: 12, lineHeight: 18, color: '#263b30' }, userMessageText: { color: '#fff' }, speakAgain: { color: '#176b45', fontSize: 10, fontWeight: '700', marginTop: 6 }, thinking: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 10 }, voiceError: { color: '#a34b34', fontSize: 10, marginTop: 8 }, composer: { flexDirection: 'row', gap: 7, alignItems: 'center', marginTop: 12 }, questionInput: { flex: 1, minWidth: 0, borderWidth: 1, borderColor: '#dce5dd', borderRadius: 11, paddingHorizontal: 11, paddingVertical: 10, fontSize: 12, color: '#173126' }, micButton: { width: 40, height: 40, borderRadius: 13, backgroundColor: '#edf4ee', alignItems: 'center', justifyContent: 'center' }, micActive: { backgroundColor: '#f9dfd9' }, micText: { fontSize: 16, color: '#245b42' }, sendButton: { height: 40, minWidth: 46, borderRadius: 11, backgroundColor: '#245b42', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 10 }, sendText: { fontSize: 11, color: '#fff', fontWeight: '800' }, assistantFootnote: { fontSize: 9, lineHeight: 13, color: '#849087', marginTop: 9 },
  subtitle: { color: '#5c6c62', fontSize: 13, marginTop: 12, marginBottom: 16 }, card: { backgroundColor: '#fff', borderRadius: 17, padding: 15, marginBottom: 11, borderWidth: 1, borderColor: '#e2e9e1' }, label: { fontSize: 10, letterSpacing: 1, fontWeight: '800', color: '#748078', marginBottom: 9 }, input: { borderWidth: 1, borderColor: '#e3e9e5', borderRadius: 11, paddingHorizontal: 12, paddingVertical: 11, fontSize: 14, color: '#173126', backgroundColor: '#fbfcfb' }, chips: { flexDirection: 'row', gap: 7, paddingTop: 9 }, chip: { paddingHorizontal: 11, paddingVertical: 7, backgroundColor: '#f1f4f1', borderRadius: 20 }, chipSelected: { backgroundColor: '#dfeee2' }, chipText: { fontSize: 11, fontWeight: '600', color: '#5f7067' }, chipTextSelected: { color: '#176b45' }, locationChip: { paddingHorizontal: 11, paddingVertical: 7, backgroundColor: '#edf5ef', borderRadius: 20 }, locationText: { fontSize: 11, fontWeight: '700', color: '#176b45' }, placeText: { fontSize: 14, color: '#173126' }, helper: { fontSize: 10, color: '#78877e', lineHeight: 15, marginTop: 8 }, rangeRow: { flexDirection: 'row', alignItems: 'center', gap: 8 }, rangeInput: { fontSize: 27, fontWeight: '800', color: '#173126', minWidth: 62, paddingVertical: 0 }, unit: { fontSize: 15, fontWeight: '700', color: '#52635a' }, caution: { marginLeft: 'auto', fontSize: 10, color: '#77867e' }, track: { height: 5, backgroundColor: '#ecf1ed', borderRadius: 4, marginTop: 12, overflow: 'hidden' }, fill: { height: 5, backgroundColor: '#23a36c', borderRadius: 4 }, primary: { height: 51, borderRadius: 14, backgroundColor: '#245b42', alignItems: 'center', justifyContent: 'center', marginTop: 1 }, primaryBusy: { opacity: 0.8 }, primaryText: { fontSize: 14, color: '#fff', fontWeight: '800' }, notice: { fontSize: 11, color: '#68786e', lineHeight: 16, marginTop: 9, marginBottom: 13 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 9 }, sectionTitle: { fontSize: 16, fontWeight: '800', color: '#20382d' }, count: { fontSize: 10, color: '#77867e' }, bestCard: { backgroundColor: '#173f2e', borderRadius: 18, padding: 15, marginBottom: 13 }, bestHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 6 }, bestLabel: { fontSize: 9, color: '#a8dfbf', fontWeight: '800', letterSpacing: 0.8 }, status: { fontSize: 9, paddingHorizontal: 8, paddingVertical: 5, borderRadius: 12, overflow: 'hidden' }, statusOk: { color: '#e2f7e9', backgroundColor: '#286246' }, statusWarn: { color: '#ffebc4', backgroundColor: '#72552b' }, bestName: { fontSize: 18, color: '#fff', fontWeight: '800', marginTop: 13 }, bestAddress: { fontSize: 11, color: '#c4d5ca', marginTop: 4 }, metrics: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 17, marginBottom: 15 }, metric: { flex: 1 }, metricLabel: { fontSize: 8, color: '#b8cec0', letterSpacing: 0.4, fontWeight: '700' }, metricValue: { fontSize: 12, color: '#fff', fontWeight: '700', marginTop: 5 }, navigation: { backgroundColor: '#f4f8f5', borderRadius: 11, padding: 11, alignItems: 'center' }, navigationText: { color: '#17603f', fontSize: 12, fontWeight: '800' }, listHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 4, marginBottom: 4, gap: 4 }, sort: { fontSize: 8, color: '#819087', letterSpacing: 0.4, fontWeight: '700' }, station: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: '#e3eae4', gap: 10 }, marker: { width: 33, height: 33, borderRadius: 11, backgroundColor: '#e5f0e6', alignItems: 'center', justifyContent: 'center' }, markerText: { fontSize: 14, color: '#287750' }, stationDetails: { flex: 1 }, stationName: { fontSize: 12, fontWeight: '700', color: '#263b30' }, stationAddress: { fontSize: 10, color: '#68786e', marginTop: 3 }, stationMeta: { fontSize: 9, color: '#95a099', marginTop: 3 }, stationTime: { alignItems: 'flex-end' }, time: { fontSize: 12, fontWeight: '800', color: '#273b30' }, reach: { fontSize: 9, marginTop: 3, fontWeight: '700' }, reachOk: { color: '#168457' }, reachWarn: { color: '#bd7a18' }, disclaimer: { fontSize: 9, color: '#7c8981', lineHeight: 14, marginTop: 17 },
});

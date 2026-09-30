import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/api_client.dart';

const _ink = Color(0xFF102C2B);
const _mutedInk = Color(0xFF607370);
const _canvas = Color(0xFFF2F5F3);
const _line = Color(0xFFDDE5E1);
const _lime = Color(0xFFD9F177);
const _green = Color(0xFF14745B);
const _red = Color(0xFFB84038);

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  static const _urlKey = 'api_base_url';

  late ScalperApi _api;
  Timer? _poller;
  Map<String, dynamic>? _status;
  List<Map<String, dynamic>> _traces = [];
  String _baseUrl = 'http://127.0.0.1:8000';
  String? _error;
  String? _lastScanStatus;
  bool _loading = true;
  bool _refreshing = false;
  bool _scanning = false;
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    _api = ScalperApi(_baseUrl);
    _initialize();
  }

  Future<void> _initialize() async {
    final preferences = await SharedPreferences.getInstance();
    final savedUrl = preferences.getString(_urlKey);
    if (!mounted) return;
    if (savedUrl != null && savedUrl.isNotEmpty) {
      _baseUrl = savedUrl;
      _api.close();
      _api = ScalperApi(_baseUrl);
    }
    await _refresh();
    _poller = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
  }

  @override
  void dispose() {
    _poller?.cancel();
    _api.close();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_refreshing) return;
    _refreshing = true;
    try {
      final values = await Future.wait([
        _api.fetchStatus(),
        _api.fetchTraces(),
      ]);
      if (!mounted) return;
      setState(() {
        _status = values[0] as Map<String, dynamic>;
        _traces = values[1] as List<Map<String, dynamic>>;
        _error = null;
        _loading = false;
      });
    } on Exception catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.toString();
        _loading = false;
      });
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _scan() async {
    setState(() => _scanning = true);
    try {
      final result = await _api.scanNow();
      _lastScanStatus = result['status']?.toString();
      if (!mounted) return;
      _showMessage(_scanMessage(result));
      await _refresh();
    } on Exception catch (error) {
      if (mounted) _showMessage(error.toString());
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  String _scanMessage(Map<String, dynamic> result) {
    final status = result['status']?.toString() ?? 'Scan complete';
    switch (status) {
      case 'ORDERS_EXECUTED':
        return 'Signal executed: ${result['placed_orders_count'] ?? 0} order(s).';
      case 'WAITING_FOR_DATA':
        return 'No completed market candles are available yet.';
      case 'NO_SIGNAL':
        return 'Scan complete. No engulfing setup found.';
      case 'CIRCUIT_BREAKER_TRIPPED':
        return 'Daily drawdown limit reached. Trading is locked.';
      case 'RISK_REJECTED':
        return 'Signal blocked by risk controls.';
      case 'MAX_ORDERS_REACHED':
        return 'Maximum open order count reached.';
      default:
        return status.replaceAll('_', ' ').toLowerCase();
    }
  }

  Future<void> _confirmEmergencyClose() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Close all open positions?'),
        content: const Text(
          'This sends an immediate close request to the active broker. This action cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton.icon(
            style: FilledButton.styleFrom(backgroundColor: _red),
            onPressed: () => Navigator.pop(context, true),
            icon: const Icon(Icons.warning_amber_rounded),
            label: const Text('Close positions'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _closing = true);
    try {
      final result = await _api.emergencyCloseAll();
      if (mounted) {
        _showMessage('Closed ${result['closed_positions'] ?? 0} position(s).');
        await _refresh();
      }
    } on Exception catch (error) {
      if (mounted) _showMessage(error.toString());
    } finally {
      if (mounted) setState(() => _closing = false);
    }
  }

  Future<void> _showSettings() async {
    final controller = TextEditingController(text: _baseUrl);
    final saved = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Container(
          padding: const EdgeInsets.fromLTRB(24, 12, 24, 28),
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(8)),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 38,
                    height: 4,
                    decoration: BoxDecoration(
                      color: _line,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                ),
                const SizedBox(height: 22),
                Text('Connection', style: _headingStyle(fontSize: 22)),
                const SizedBox(height: 6),
                const Text(
                  'Enter the address where the FastAPI service is running.',
                  style: TextStyle(color: _mutedInk),
                ),
                const SizedBox(height: 18),
                TextField(
                  controller: controller,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: InputDecoration(
                    labelText: 'API base URL',
                    hintText: 'http://127.0.0.1:8000',
                    prefixIcon: const Icon(Icons.link_rounded),
                    filled: true,
                    fillColor: _canvas,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(6),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 18),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: () =>
                        Navigator.pop(context, controller.text.trim()),
                    child: const Text('Save connection'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    controller.dispose();
    if (saved == null || saved.isEmpty || !mounted) return;
    final normalized = saved.replaceFirst(RegExp(r'/+$'), '');
    _api.close();
    _api = ScalperApi(normalized);
    _baseUrl = normalized;
    await (await SharedPreferences.getInstance()).setString(
      _urlKey,
      normalized,
    );
    setState(() {
      _loading = true;
      _status = null;
      _error = null;
    });
    await _refresh();
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _topBar(status),
            Expanded(
              child: _loading && status == null
                  ? const Center(child: CircularProgressIndicator())
                  : status == null
                  ? _connectionError()
                  : RefreshIndicator(
                      onRefresh: _refresh,
                      color: _green,
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          final wide = constraints.maxWidth >= 1050;
                          return SingleChildScrollView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: EdgeInsets.fromLTRB(
                              constraints.maxWidth > 1400 ? 54 : 24,
                              12,
                              constraints.maxWidth > 1400 ? 54 : 24,
                              40,
                            ),
                            child: Center(
                              child: ConstrainedBox(
                                constraints: const BoxConstraints(
                                  maxWidth: 1440,
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    if (_error != null) ...[
                                      _staleBanner(),
                                      const SizedBox(height: 16),
                                    ],
                                    if (_isPaperFallback(status)) ...[
                                      _fallbackBanner(),
                                      const SizedBox(height: 16),
                                    ],
                                    _accountHero(status, wide),
                                    const SizedBox(height: 18),
                                    _riskOverview(status, wide),
                                    const SizedBox(height: 30),
                                    if (wide)
                                      Row(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Expanded(
                                            flex: 6,
                                            child: _positionsSection(status),
                                          ),
                                          const SizedBox(width: 24),
                                          Expanded(
                                            flex: 4,
                                            child: _activitySection(),
                                          ),
                                        ],
                                      )
                                    else ...[
                                      _positionsSection(status),
                                      const SizedBox(height: 32),
                                      _activitySection(),
                                    ],
                                    const SizedBox(height: 30),
                                    _actions(status),
                                    const SizedBox(height: 20),
                                    _footer(status),
                                  ],
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _topBar(Map<String, dynamic>? status) {
    final connected = status != null && _error == null;
    final activeMode = status?['active_mode']?.toString() ?? 'paper';
    final compact = MediaQuery.sizeOf(context).width < 400;
    return Padding(
      padding: EdgeInsets.fromLTRB(
        compact ? 16 : 24,
        15,
        compact ? 12 : 22,
        10,
      ),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: _ink,
              borderRadius: BorderRadius.circular(7),
            ),
            child: const Icon(
              Icons.candlestick_chart_rounded,
              color: _lime,
              size: 21,
            ),
          ),
          const SizedBox(width: 11),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'NORTHSTAR',
                style: _headingStyle(fontSize: 15, weight: FontWeight.w700),
              ),
              Text(
                'TRADING DESK',
                style: TextStyle(
                  color: _mutedInk,
                  fontSize: 9,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                ),
              ),
            ],
          ),
          const Spacer(),
          if (status != null && !compact) ...[
            _modePill(activeMode),
            const SizedBox(width: 9),
          ],
          _connectionPill(connected),
          const SizedBox(width: 4),
          IconButton(
            tooltip: 'Connection settings',
            onPressed: _showSettings,
            icon: const Icon(Icons.tune_rounded, color: _ink),
          ),
        ],
      ),
    );
  }

  Widget _modePill(String mode) {
    final live = mode == 'mt5';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: live ? const Color(0xFFE3F2EC) : const Color(0xFFE8ECEA),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            live ? Icons.bolt_rounded : Icons.science_outlined,
            size: 13,
            color: live ? _green : _mutedInk,
          ),
          const SizedBox(width: 5),
          Text(
            live ? 'MT5 ACTIVE' : 'PAPER',
            style: TextStyle(
              color: live ? _green : _mutedInk,
              fontSize: 10,
              fontWeight: FontWeight.w800,
              letterSpacing: .6,
            ),
          ),
        ],
      ),
    );
  }

  Widget _connectionPill(bool connected) {
    final color = connected ? _green : _red;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: _line),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            connected ? 'CONNECTED' : 'OFFLINE',
            style: TextStyle(
              color: color,
              fontSize: 9,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }

  Widget _accountHero(Map<String, dynamic> status, bool wide) {
    final balance = _number(status['balance']);
    final equity = _number(status['equity']);
    final pnl = equity - balance;
    final columns = wide ? CrossAxisAlignment.start : CrossAxisAlignment.start;
    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(wide ? 30 : 22),
      decoration: BoxDecoration(
        color: _ink,
        borderRadius: BorderRadius.circular(7),
        boxShadow: const [
          BoxShadow(
            color: Color(0x14213935),
            blurRadius: 20,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: columns,
        children: [
          Row(
            children: [
              const _Eyebrow('ACCOUNT OVERVIEW', color: Color(0xFFB6C8C1)),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
                decoration: BoxDecoration(
                  border: Border.all(color: const Color(0x4FFFFFFF)),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  '${status['symbol'] ?? 'NAS100'}  /  M5',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 22),
          if (wide)
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(child: _balanceValue(balance, equity, pnl)),
                _heroActions(),
              ],
            )
          else ...[
            _balanceValue(balance, equity, pnl),
            const SizedBox(height: 22),
            _heroActions(compact: true),
          ],
        ],
      ),
    );
  }

  Widget _balanceValue(double balance, double equity, double pnl) {
    final pnlColor = pnl >= 0 ? _lime : const Color(0xFFFFA197);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Balance',
          style: TextStyle(color: Color(0xFFB6C8C1), fontSize: 12),
        ),
        const SizedBox(height: 4),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(
            _money(balance),
            style: GoogleFonts.spaceGrotesk(
              color: Colors.white,
              fontSize: 42,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(height: 11),
        Wrap(
          spacing: 13,
          runSpacing: 5,
          children: [
            _inlineValue('Equity', _money(equity)),
            _inlineValue(
              'Floating P/L',
              '${pnl >= 0 ? '+' : '-'}${_money(pnl.abs())}',
              color: pnlColor,
            ),
          ],
        ),
      ],
    );
  }

  Widget _inlineValue(
    String label,
    String value, {
    Color color = Colors.white,
  }) {
    return RichText(
      text: TextSpan(
        style: const TextStyle(fontSize: 11, color: Color(0xFFB6C8C1)),
        children: [
          TextSpan(text: '$label  '),
          TextSpan(
            text: value,
            style: TextStyle(color: color, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }

  Widget _heroActions({bool compact = false}) {
    final buttons = [
      FilledButton.icon(
        onPressed: _scanning ? null : _scan,
        style: FilledButton.styleFrom(
          backgroundColor: _lime,
          foregroundColor: _ink,
          padding: const EdgeInsets.symmetric(horizontal: 17, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
        ),
        icon: _scanning
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.radar_rounded, size: 17),
        label: Text(_scanning ? 'Scanning' : 'Scan now'),
      ),
      const SizedBox(width: 9, height: 9),
      OutlinedButton.icon(
        onPressed: _closing ? null : _confirmEmergencyClose,
        style: OutlinedButton.styleFrom(
          foregroundColor: Colors.white,
          side: const BorderSide(color: Color(0x607F9690)),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
        ),
        icon: _closing
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : const Icon(Icons.power_settings_new_rounded, size: 16),
        label: Text(_closing ? 'Closing' : 'Emergency close'),
      ),
    ];
    if (compact) {
      return Wrap(
        spacing: 8,
        runSpacing: 8,
        children: buttons.whereType<Widget>().toList(),
      );
    }
    return Row(mainAxisSize: MainAxisSize.min, children: buttons);
  }

  Widget _riskOverview(Map<String, dynamic> status, bool wide) {
    final drawdown = _number(status['current_drawdown_pct']).clamp(0.0, 100.0);
    final drawdownLimit = _number(status['daily_drawdown_limit_pct']);
    final risk = _number(status['active_risk_pct']);
    final riskLimit = _number(status['max_total_risk_pct']);
    final orders = _number(status['active_orders_count']).toInt();
    final maxOrders = _number(status['max_active_orders']).toInt();
    final items = [
      _riskTile(
        title: 'DAILY DRAWDOWN',
        value: '${_percent(_number(status['current_drawdown_pct']))}%',
        note: 'Limit ${_percent(drawdownLimit)}%',
        fraction: drawdownLimit > 0 ? drawdown / drawdownLimit : 0,
        tint: drawdown >= drawdownLimit ? _red : _green,
        icon: Icons.trending_down_rounded,
      ),
      _riskTile(
        title: 'ACTIVE RISK',
        value: '${_percent(risk)}%',
        note: '${_money(_number(status['active_risk_usd']))} at risk',
        fraction: riskLimit > 0 ? risk / riskLimit : 0,
        tint: _green,
        icon: Icons.shield_outlined,
      ),
      _riskTile(
        title: 'OPEN ORDERS',
        value: '$orders  /  $maxOrders',
        note:
            'Profit target ${_percent(_number(status['profit_target_pct_per_order']))}% per order',
        fraction: maxOrders > 0 ? orders / maxOrders : 0,
        tint: _ink,
        icon: Icons.stacked_line_chart_rounded,
      ),
    ];
    if (wide) {
      return Row(
        children: [
          for (var i = 0; i < items.length; i++) ...[
            Expanded(child: items[i]),
            if (i != items.length - 1) const SizedBox(width: 14),
          ],
        ],
      );
    }
    return Column(
      children: [
        for (final item in items) ...[item, const SizedBox(height: 10)],
      ],
    );
  }

  Widget _riskTile({
    required String title,
    required String value,
    required String note,
    required double fraction,
    required Color tint,
    required IconData icon,
  }) {
    return Container(
      padding: const EdgeInsets.all(17),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: _line),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: _mutedInk),
              const SizedBox(width: 7),
              Expanded(child: _Eyebrow(title, color: _mutedInk)),
            ],
          ),
          const SizedBox(height: 13),
          Text(
            value,
            style: _headingStyle(fontSize: 24, weight: FontWeight.w600),
          ),
          const SizedBox(height: 3),
          Text(note, style: const TextStyle(color: _mutedInk, fontSize: 11)),
          const SizedBox(height: 14),
          ClipRRect(
            borderRadius: BorderRadius.circular(5),
            child: LinearProgressIndicator(
              value: fraction.clamp(0.0, 1.0).toDouble(),
              minHeight: 4,
              color: tint,
              backgroundColor: _canvas,
            ),
          ),
        ],
      ),
    );
  }

  Widget _positionsSection(Map<String, dynamic> status) {
    final positions = (status['open_positions'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionHeader('Open positions', '${positions.length} ACTIVE'),
        const SizedBox(height: 12),
        if (positions.isEmpty)
          _emptyState(
            icon: Icons.stacked_line_chart_rounded,
            title: 'No open positions',
            subtitle: 'Positions opened by the active broker will appear here.',
          )
        else ...[
          if (MediaQuery.sizeOf(context).width > 650) _positionColumnHeader(),
          for (final position in positions) _positionRow(position),
        ],
      ],
    );
  }

  Widget _positionColumnHeader() {
    return const Padding(
      padding: EdgeInsets.fromLTRB(12, 8, 12, 9),
      child: Row(
        children: [
          Expanded(flex: 3, child: _Eyebrow('POSITION', color: _mutedInk)),
          Expanded(flex: 2, child: _Eyebrow('ENTRY / LOTS', color: _mutedInk)),
          Expanded(flex: 2, child: _Eyebrow('STOP / TARGET', color: _mutedInk)),
          Expanded(flex: 2, child: _Eyebrow('FLOATING P/L', color: _mutedInk)),
        ],
      ),
    );
  }

  Widget _positionRow(Map<String, dynamic> position) {
    final direction =
        position['order_type']?.toString().split('.').last.toUpperCase() ??
        'ORDER';
    final isBuy = direction == 'BUY';
    final profit = _number(position['current_profit']);
    final compact = MediaQuery.sizeOf(context).width < 650;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: _line),
        borderRadius: BorderRadius.circular(5),
      ),
      child: compact
          ? Column(
              children: [
                Row(
                  children: [
                    _directionTag(direction, isBuy),
                    const SizedBox(width: 9),
                    Text(
                      '#${position['ticket'] ?? '-'}',
                      style: _monoStyle(fontSize: 11),
                    ),
                    const Spacer(),
                    Text(
                      '${profit >= 0 ? '+' : '-'}${_money(profit.abs())}',
                      style: _monoStyle(
                        color: profit >= 0 ? _green : _red,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 11),
                Row(
                  children: [
                    Expanded(
                      child: _compactDetail(
                        'ENTRY',
                        _price(position['open_price']),
                      ),
                    ),
                    Expanded(
                      child: _compactDetail(
                        'LOTS',
                        _number(position['lots']).toStringAsFixed(2),
                      ),
                    ),
                    Expanded(
                      child: _compactDetail('STOP', _price(position['sl'])),
                    ),
                    Expanded(
                      child: _compactDetail('TARGET', _price(position['tp'])),
                    ),
                  ],
                ),
              ],
            )
          : Row(
              children: [
                Expanded(
                  flex: 3,
                  child: Row(
                    children: [
                      _directionTag(direction, isBuy),
                      const SizedBox(width: 9),
                      Text(
                        '#${position['ticket'] ?? '-'}',
                        style: _monoStyle(fontSize: 11),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  flex: 2,
                  child: Text(
                    '${_price(position['open_price'])}  /  ${_number(position['lots']).toStringAsFixed(2)}',
                    style: _monoStyle(fontSize: 11),
                  ),
                ),
                Expanded(
                  flex: 2,
                  child: Text(
                    '${_price(position['sl'])}  /  ${_price(position['tp'])}',
                    style: _monoStyle(fontSize: 11),
                  ),
                ),
                Expanded(
                  flex: 2,
                  child: Text(
                    '${profit >= 0 ? '+' : '-'}${_money(profit.abs())}',
                    style: _monoStyle(
                      color: profit >= 0 ? _green : _red,
                      fontSize: 11,
                    ),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _compactDetail(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Eyebrow(label, color: _mutedInk),
        const SizedBox(height: 4),
        Text(value, style: _monoStyle(fontSize: 10)),
      ],
    );
  }

  Widget _directionTag(String direction, bool isBuy) {
    final color = isBuy ? _green : _red;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 5),
      decoration: BoxDecoration(
        color: isBuy ? const Color(0xFFE8F2EC) : const Color(0xFFFAE9E7),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Text(
        direction,
        style: TextStyle(
          color: color,
          fontSize: 9,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }

  Widget _activitySection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionHeader('Activity', 'DATABASE TRACE'),
        const SizedBox(height: 12),
        if (_traces.isEmpty)
          _emptyState(
            icon: Icons.receipt_long_rounded,
            title: 'No recorded activity',
            subtitle:
                'Trades and risk events saved by the backend will show here.',
          )
        else
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 15),
            decoration: BoxDecoration(
              color: Colors.white,
              border: Border.all(color: _line),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Column(
              children: [
                for (var i = 0; i < _traces.length; i++)
                  _traceRow(_traces[i], last: i == _traces.length - 1),
              ],
            ),
          ),
      ],
    );
  }

  Widget _traceRow(Map<String, dynamic> trace, {required bool last}) {
    final type = trace['event_type']?.toString() ?? 'EVENT';
    final payload = trace['payload'] is Map
        ? trace['payload'] as Map
        : const {};
    final detail =
        payload['reason']?.toString() ??
        payload['signal']?.toString() ??
        payload['type']?.toString() ??
        trace['symbol']?.toString() ??
        'Bot event';
    final date = DateTime.tryParse(trace['recorded_at']?.toString() ?? '')
        ?.toLocal();
    final time = date == null
        ? 'TIME UNKNOWN'
        : DateFormat('MMM d  HH:mm').format(date);
    final critical = type.contains('CIRCUIT') || type.contains('EMERGENCY');
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: BoxDecoration(
        border: last ? null : const Border(bottom: BorderSide(color: _line)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 29,
            height: 29,
            decoration: BoxDecoration(
              color: critical
                  ? const Color(0xFFFFE8E4)
                  : const Color(0xFFE8F2EC),
              borderRadius: BorderRadius.circular(5),
            ),
            child: Icon(
              critical ? Icons.priority_high_rounded : _eventIcon(type),
              size: 15,
              color: critical ? _red : _green,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  type.replaceAll('_', ' '),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  detail,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 10, color: _mutedInk),
                ),
                const SizedBox(height: 4),
                Text(
                  time.toUpperCase(),
                  style: _monoStyle(color: _mutedInk, fontSize: 9),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  IconData _eventIcon(String type) {
    if (type.contains('ORDER') || type.contains('SETUP')) {
      return Icons.swap_horiz_rounded;
    }
    if (type.contains('REJECT')) return Icons.block_rounded;
    if (type.contains('SIGNAL')) return Icons.bolt_rounded;
    return Icons.radio_button_checked_rounded;
  }

  Widget _actions(Map<String, dynamic> status) {
    final tripped = status['circuit_breaker_tripped'] == true;
    final reason = status['circuit_breaker_reason']?.toString();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
      decoration: BoxDecoration(
        color: tripped ? const Color(0xFFFFEFED) : const Color(0xFFE8F0EC),
        borderRadius: BorderRadius.circular(5),
        border: Border.all(color: tripped ? const Color(0xFFF2C9C4) : _line),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            tripped ? Icons.lock_clock_rounded : Icons.verified_user_outlined,
            size: 18,
            color: tripped ? _red : _green,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  tripped ? 'Circuit breaker engaged' : 'Risk controls active',
                  style: TextStyle(
                    color: tripped ? _red : _green,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                if (tripped && reason != null && reason.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(
                    reason,
                    style: const TextStyle(color: _mutedInk, fontSize: 11),
                  ),
                ] else ...[
                  const SizedBox(height: 3),
                  const Text(
                    'Trade sizing and daily loss limits are enforced by the backend.',
                    style: TextStyle(color: _mutedInk, fontSize: 11),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _footer(Map<String, dynamic> status) {
    final lastScan = _lastScanStatus?.replaceAll('_', ' ').toLowerCase();
    return Row(
      children: [
        const Icon(Icons.storage_rounded, color: _mutedInk, size: 14),
        const SizedBox(width: 6),
        const Expanded(
          child: Text(
            'Trace history served by backend database',
            style: TextStyle(color: _mutedInk, fontSize: 10),
          ),
        ),
        if (lastScan != null)
          Text(
            'LAST SCAN  $lastScan',
            style: _monoStyle(color: _mutedInk, fontSize: 9),
          ),
        if (lastScan != null) const SizedBox(width: 12),
        Text(
          'UPDATED ${DateFormat('HH:mm:ss').format(DateTime.now())}',
          style: _monoStyle(color: _mutedInk, fontSize: 9),
        ),
      ],
    );
  }

  Widget _sectionHeader(String title, String trailing) {
    return Row(
      children: [
        Text(
          title,
          style: _headingStyle(fontSize: 19, weight: FontWeight.w600),
        ),
        const Spacer(),
        Text(
          trailing,
          style: const TextStyle(
            color: _mutedInk,
            fontSize: 9,
            fontWeight: FontWeight.w800,
            letterSpacing: .8,
          ),
        ),
      ],
    );
  }

  Widget _emptyState({
    required IconData icon,
    required String title,
    required String subtitle,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: _line),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        children: [
          Icon(icon, color: _mutedInk, size: 22),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  style: const TextStyle(color: _mutedInk, fontSize: 11),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _staleBanner() {
    return _notice(
      icon: Icons.cloud_off_rounded,
      color: _red,
      background: const Color(0xFFFFEFED),
      text: 'Connection interrupted. Showing the last received account state.',
      trailing: IconButton(
        tooltip: 'Retry connection',
        onPressed: _refresh,
        icon: const Icon(Icons.refresh_rounded, size: 18),
      ),
    );
  }

  Widget _fallbackBanner() {
    return _notice(
      icon: Icons.info_outline_rounded,
      color: const Color(0xFF76500A),
      background: const Color(0xFFFFF4D9),
      text: 'MT5 was configured, but the active broker is paper simulation.',
      trailing: const SizedBox(width: 4),
    );
  }

  Widget _notice({
    required IconData icon,
    required Color color,
    required Color background,
    required String text,
    required Widget trailing,
  }) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 7, 6, 7),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(5),
      ),
      child: Row(
        children: [
          Icon(icon, size: 17, color: color),
          const SizedBox(width: 9),
          Expanded(
            child: Text(text, style: TextStyle(color: color, fontSize: 11)),
          ),
          trailing,
        ],
      ),
    );
  }

  Widget _connectionError() {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: Padding(
          padding: const EdgeInsets.all(26),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.portable_wifi_off_rounded,
                color: _red,
                size: 34,
              ),
              const SizedBox(height: 14),
              Text('API not reachable', style: _headingStyle(fontSize: 22)),
              const SizedBox(height: 8),
              Text(
                _error ?? 'Check that the backend is running and the API URL is correct.',
                textAlign: TextAlign.center,
                style: const TextStyle(color: _mutedInk, fontSize: 12),
              ),
              const SizedBox(height: 17),
              Wrap(
                spacing: 9,
                runSpacing: 8,
                alignment: WrapAlignment.center,
                children: [
                  FilledButton.icon(
                    onPressed: _refresh,
                    icon: const Icon(Icons.refresh_rounded),
                    label: const Text('Retry'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _showSettings,
                    icon: const Icon(Icons.tune_rounded),
                    label: const Text('Connection settings'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  bool _isPaperFallback(Map<String, dynamic> status) =>
      status['mode'] == 'mt5' && status['active_mode'] == 'paper';
}

class _Eyebrow extends StatelessWidget {
  const _Eyebrow(this.text, {this.color = _mutedInk});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Text(
    text,
    maxLines: 1,
    overflow: TextOverflow.ellipsis,
    style: TextStyle(
      color: color,
      fontSize: 9,
      fontWeight: FontWeight.w800,
      letterSpacing: .75,
    ),
  );
}

TextStyle _headingStyle({
  required double fontSize,
  FontWeight weight = FontWeight.w700,
}) => GoogleFonts.spaceGrotesk(
  color: _ink,
  fontSize: fontSize,
  fontWeight: weight,
);

TextStyle _monoStyle({Color color = _ink, required double fontSize}) =>
    GoogleFonts.ibmPlexMono(
      color: color,
      fontSize: fontSize,
      fontWeight: FontWeight.w500,
    );

double _number(Object? value) => value is num ? value.toDouble() : 0;

String _money(double value) =>
    NumberFormat.currency(symbol: r'$', decimalDigits: 2).format(value);

String _price(Object? value) {
  final number = _number(value);
  return number == 0 ? '-' : NumberFormat('#,##0.00').format(number);
}

String _percent(double value) => NumberFormat('0.0').format(value);

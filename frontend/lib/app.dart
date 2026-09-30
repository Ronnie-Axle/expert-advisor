import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'screens/dashboard_page.dart';

const _ink = Color(0xFF102C2B);
const _canvas = Color(0xFFF2F5F3);
const _green = Color(0xFF14745B);

class ScalperApp extends StatelessWidget {
  const ScalperApp({super.key});

  @override
  Widget build(BuildContext context) {
    final base = ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: _green),
      scaffoldBackgroundColor: _canvas,
      useMaterial3: true,
    );
    return MaterialApp(
      title: 'NAS100 Scalper',
      debugShowCheckedModeBanner: false,
      theme: base.copyWith(
        textTheme: GoogleFonts.dmSansTextTheme(base.textTheme)
            .apply(bodyColor: _ink, displayColor: _ink),
        appBarTheme: const AppBarTheme(
          backgroundColor: _canvas,
          foregroundColor: _ink,
          elevation: 0,
        ),
      ),
      home: const DashboardPage(),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'services/product_api.dart';

class AccountProfileSettingsScreen extends StatefulWidget {
  const AccountProfileSettingsScreen({
    required this.email,
    this.hasGoogleIdentity = false,
    required this.products,
    this.onNameChanged,
    super.key,
  });

  final String email;
  final bool hasGoogleIdentity;
  final ProductGateway products;
  final Future<void> Function()? onNameChanged;

  @override
  State<AccountProfileSettingsScreen> createState() =>
      _AccountProfileSettingsScreenState();
}

class _AccountProfileSettingsScreenState
    extends State<AccountProfileSettingsScreen> {
  late Future<AccountProfile> _profile = widget.products.accountProfile();

  @override
  Widget build(BuildContext context) => FutureBuilder<AccountProfile>(
    future: _profile,
    builder: (context, snapshot) {
      if (snapshot.hasError) {
        return Scaffold(
          appBar: AppBar(title: const Text('Profile')),
          body: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'Could not load your private profile: ${snapshot.error}',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: () => setState(
                      () => _profile = widget.products.accountProfile(),
                    ),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
        );
      }
      if (!snapshot.hasData) {
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      }
      return AccountProfileEditor(
        initial: snapshot.data!,
        email: widget.email,
        hasGoogleIdentity: widget.hasGoogleIdentity,
        products: widget.products,
        onboarding: false,
        onSaved: (saved) async {
          await widget.onNameChanged?.call();
          if (context.mounted) Navigator.pop(context, saved);
        },
      );
    },
  );
}

class AccountProfileEditor extends StatefulWidget {
  const AccountProfileEditor({
    required this.initial,
    required this.email,
    this.hasGoogleIdentity = false,
    required this.products,
    required this.onboarding,
    required this.onSaved,
    this.onSignOut,
    super.key,
  });

  final AccountProfile initial;
  final String email;
  final bool hasGoogleIdentity;
  final ProductGateway products;
  final bool onboarding;
  final Future<void> Function(AccountProfile profile) onSaved;
  final Future<void> Function()? onSignOut;

  @override
  State<AccountProfileEditor> createState() => _AccountProfileEditorState();
}

class _AccountProfileEditorState extends State<AccountProfileEditor> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _dateOfBirth;
  late final TextEditingController _phone;
  late final TextEditingController _country;
  late Future<ProfileSnapshot> _healthProfile;
  DateTime? _selectedDateOfBirth;
  late String _unitSystem;
  late bool _researchConsent;
  late bool _acceptedLegal;
  var _goal = 'balanced';
  var _customGoal = '';
  var _dietaryStyle = 'No specific diet';
  var _customDietaryStyle = '';
  var _healthConditions = <String>[];
  var _personalizationConsent = false;
  var _removePhone = false;
  var _currentStep = 0;
  var _saving = false;
  String? _notice;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.initial.fullName);
    _selectedDateOfBirth = widget.initial.dateOfBirth;
    _dateOfBirth = TextEditingController(
      text: _formatDate(widget.initial.dateOfBirth),
    );
    _phone = TextEditingController();
    _country = TextEditingController(text: widget.initial.countryRegion ?? '');
    _unitSystem = widget.initial.unitSystem;
    _researchConsent = widget.initial.researchInsightsConsent;
    _acceptedLegal = widget.initial.legalAcceptanceComplete;
    _healthProfile = widget.products.profile().then((profile) {
      _goal = profile.goal;
      _customGoal = profile.customGoal ?? '';
      _dietaryStyle = profile.dietaryStyle;
      _customDietaryStyle = profile.customDietaryStyle ?? '';
      _healthConditions = List.from(profile.healthConditions);
      _personalizationConsent = profile.consentPersonalization;
      return profile;
    });
  }

  @override
  void dispose() {
    _name.dispose();
    _dateOfBirth.dispose();
    _phone.dispose();
    _country.dispose();
    super.dispose();
  }

  Future<void> _pickDateOfBirth() async {
    final today = DateTime.now();
    final chosen = await showDatePicker(
      context: context,
      initialDate: _selectedDateOfBirth ?? DateTime(today.year - 18),
      firstDate: DateTime(today.year - 120, today.month, today.day),
      lastDate: DateTime(today.year - 18, today.month, today.day),
      helpText: 'Select date of birth',
    );
    if (chosen != null && mounted) {
      setState(() {
        _selectedDateOfBirth = chosen;
        _dateOfBirth.text = _formatDate(chosen);
      });
    }
  }

  Future<void> _save(ProfileSnapshot currentHealthProfile) async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedDateOfBirth == null) {
      setState(() => _notice = 'Select your date of birth to continue.');
      return;
    }
    if (widget.onboarding && !_acceptedLegal) {
      setState(
        () => _notice =
            'Confirm that you are 18 or older and accept the Terms and Privacy Policy.',
      );
      return;
    }
    setState(() {
      _saving = true;
      _notice = null;
    });
    try {
      await widget.products.saveProfile(
        ProfileSnapshot(
          goal: _goal,
          customGoal: _goal == 'custom' ? _customGoal.trim() : null,
          dietaryStyle: _dietaryStyle,
          customDietaryStyle: _dietaryStyle == 'Custom' ? _customDietaryStyle.trim() : null,
          healthConditions: _healthConditions.where((c) => c.toLowerCase() != 'none').toList(),
          allergens: currentHealthProfile.allergens,
          dietaryPreferences: currentHealthProfile.dietaryPreferences,
          intolerances: currentHealthProfile.intolerances,
          foodExclusions: currentHealthProfile.foodExclusions,
          consentPersonalization: _personalizationConsent,
          dailyTargets: currentHealthProfile.dailyTargets,
          bodyContext: currentHealthProfile.bodyContext,
        ),
      );
      final phone = _phone.text.trim();
      final saved = await widget.products.saveAccountProfile(
        fullName: _name.text.trim(),
        dateOfBirth: _selectedDateOfBirth,
        phoneUpdate: _removePhone
            ? 'REMOVE'
            : phone.isNotEmpty
            ? 'SET'
            : 'KEEP',
        phoneNumber: phone.isEmpty ? null : phone,
        countryRegion: _country.text.trim().isEmpty
            ? null
            : _country.text.trim().toUpperCase(),
        unitSystem: _unitSystem,
        researchInsightsConsent: _researchConsent,
        completeOnboarding: widget.onboarding,
        acceptedTerms: _acceptedLegal,
        acceptedPrivacy: _acceptedLegal,
      );
      await widget.onSaved(saved);
    } on Object catch (error) {
      if (mounted) setState(() => _notice = error.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<ProfileSnapshot>(
    future: _healthProfile,
    builder: (context, snapshot) {
      if (snapshot.hasError) {
        return Scaffold(
          appBar: widget.onboarding
              ? null
              : AppBar(title: const Text('Profile')),
          body: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'Could not load your wellness profile: ${snapshot.error}',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: () => setState(
                      () => _healthProfile = widget.products.profile(),
                    ),
                    child: const Text('Retry'),
                  ),
                  if (widget.onSignOut != null)
                    TextButton(
                      onPressed: widget.onSignOut,
                      child: const Text('Sign out'),
                    ),
                ],
              ),
            ),
          ),
        );
      }
      if (!snapshot.hasData) {
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      }
      final profile = snapshot.data!;
      return Scaffold(
        appBar: AppBar(
          automaticallyImplyLeading: !widget.onboarding,
          title: Text(widget.onboarding ? 'Set up NutriLens X' : 'Profile'),
          actions: [
            if (widget.onboarding && widget.onSignOut != null)
              TextButton(
                onPressed: widget.onSignOut,
                child: const Text('Sign out'),
              ),
          ],
        ),
        body: SafeArea(
          child: Form(
            key: _formKey,
            child: Stepper(
              currentStep: _currentStep,
              onStepTapped: (value) => setState(() => _currentStep = value),
              onStepCancel: _currentStep == 0
                  ? null
                  : () => setState(() => _currentStep--),
              onStepContinue: _saving
                  ? null
                  : () {
                      if (_currentStep < 2) {
                        setState(() => _currentStep++);
                      } else {
                        _save(profile);
                      }
                    },
              controlsBuilder: (context, details) => Padding(
                padding: const EdgeInsets.only(top: 18),
                child: Row(
                  children: [
                    FilledButton(
                      key: Key(
                        details.currentStep == 2
                            ? 'save-profile'
                            : 'profile-next-${details.currentStep}',
                      ),
                      onPressed: details.onStepContinue,
                      child: _saving && _currentStep == 2
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : Text(
                              _currentStep == 2 ? 'Save profile' : 'Continue',
                            ),
                    ),
                    if (details.onStepCancel != null) ...[
                      const SizedBox(width: 8),
                      TextButton(
                        onPressed: details.onStepCancel,
                        child: const Text('Back'),
                      ),
                    ],
                  ],
                ),
              ),
              steps: [
                Step(
                  title: const Text('Your account'),
                  isActive: _currentStep >= 0,
                  content: Column(
                    children: [
                      TextFormField(
                        key: const Key('profile-full-name'),
                        controller: _name,
                        autofillHints: const [AutofillHints.name],
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          labelText: 'Full name',
                        ),
                        validator: (value) => (value?.trim().length ?? 0) < 2
                            ? 'Enter your full name.'
                            : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        initialValue: widget.email,
                        enabled: false,
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          labelText: 'Verified account email',
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Your verified account identity is reused; NutriLens does not ask you to retype it.',
                      ),
                      if (widget.onboarding &&
                          !widget.initial.legalAcceptanceComplete)
                        CheckboxListTile(
                          key: const Key('onboarding-legal-acceptance'),
                          contentPadding: EdgeInsets.zero,
                          title: const Text(
                            'I am 18 or older and agree to the Terms of Use and Privacy Policy',
                          ),
                          subtitle: const Text(
                            'https://nutrilensx.tech/terms · https://nutrilensx.tech/privacy',
                          ),
                          value: _acceptedLegal,
                          onChanged: (value) =>
                              setState(() => _acceptedLegal = value ?? false),
                        ),
                    ],
                  ),
                ),
                Step(
                  title: const Text('Basic profile'),
                  isActive: _currentStep >= 1,
                  content: Column(
                    children: [
                      TextFormField(
                        key: const Key('profile-date-of-birth'),
                        controller: _dateOfBirth,
                        readOnly: true,
                        onTap: _pickDateOfBirth,
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          labelText: 'Date of birth',
                          suffixIcon: Icon(Icons.calendar_today_outlined),
                        ),
                        validator: (_) => _selectedDateOfBirth == null
                            ? 'Select your date of birth.'
                            : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        key: const Key('profile-phone'),
                        controller: _phone,
                        enabled: !_removePhone,
                        keyboardType: TextInputType.phone,
                        autofillHints: const [AutofillHints.telephoneNumber],
                        decoration: InputDecoration(
                          border: const OutlineInputBorder(),
                          labelText: 'Phone (optional)',
                          hintText: widget.initial.maskedPhoneNumber == null
                              ? '+919876543210'
                              : 'Leave blank to keep ${widget.initial.maskedPhoneNumber}',
                        ),
                        validator: (value) {
                          final phone = value?.trim() ?? '';
                          if (phone.isEmpty || _removePhone) return null;
                          return RegExp(r'^\+[1-9]\d{7,14}$').hasMatch(phone)
                              ? null
                              : 'Use E.164 format with country code.';
                        },
                      ),
                      if (widget.initial.maskedPhoneNumber != null)
                        CheckboxListTile(
                          key: const Key('remove-profile-phone'),
                          contentPadding: EdgeInsets.zero,
                          title: Text(
                            'Remove ${widget.initial.maskedPhoneNumber}',
                          ),
                          value: _removePhone,
                          onChanged: (value) =>
                              setState(() => _removePhone = value ?? false),
                        ),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text(
                          widget.initial.phoneVerificationAvailability ==
                                  'BLOCKED_EXTERNAL_COST'
                              ? 'SMS verification is not enabled yet. A saved number remains unverified.'
                              : 'A saved number remains unverified until you complete OTP verification.',
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        key: const Key('profile-country'),
                        controller: _country,
                        textCapitalization: TextCapitalization.characters,
                        inputFormatters: [
                          FilteringTextInputFormatter.allow(RegExp('[A-Za-z]')),
                          LengthLimitingTextInputFormatter(2),
                        ],
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          labelText: 'Country/region code (optional)',
                          hintText: 'IN',
                        ),
                        validator: (value) {
                          final country = value?.trim() ?? '';
                          return country.isEmpty || country.length == 2
                              ? null
                              : 'Use a two-letter country/region code.';
                        },
                      ),
                    ],
                  ),
                ),
                Step(
                  title: const Text('Personalization'),
                  isActive: _currentStep >= 2,
                  content: Column(
                    children: [
                      DropdownButtonFormField<String>(
                        key: const Key('profile-goal'),
                        initialValue: _goal,
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          labelText: 'Nutrition goal',
                        ),
                        items: wellnessGoalLabels.entries
                            .map(
                              (entry) => DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                            )
                            .toList(),
                        onChanged: (value) =>
                            setState(() => _goal = value ?? 'balanced'),
                      ),
                      if (_goal == 'custom') ...[
                        const SizedBox(height: 12),
                        TextFormField(
                          key: const Key('profile-custom-goal'),
                          initialValue: _customGoal,
                          maxLength: 120,
                          decoration: const InputDecoration(
                            border: OutlineInputBorder(),
                            labelText: 'Describe your goal',
                            helperText:
                                'A personal intention only—not a medical or calorie prescription.',
                          ),
                          onChanged: (value) => _customGoal = value,
                          validator: (value) =>
                              _goal == 'custom' &&
                                  (value?.trim().isEmpty ?? true)
                              ? 'Describe your custom goal.'
                              : null,
                        ),
                      ],
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        key: const Key('profile-dietary-style'),
                        initialValue: _dietaryStyle,
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          labelText: 'Dietary style',
                        ),
                        items: const [
                          'No specific diet',
                          'Vegetarian',
                          'Non-vegetarian',
                          'Vegan',
                          'Eggetarian',
                          'Pescatarian',
                          'Jain',
                          'Keto',
                          'Custom',
                        ].map((s) => DropdownMenuItem(value: s, child: Text(s))).toList(),
                        onChanged: (value) =>
                            setState(() => _dietaryStyle = value ?? 'No specific diet'),
                      ),
                      if (_dietaryStyle == 'Custom') ...[
                        const SizedBox(height: 12),
                        TextFormField(
                          key: const Key('profile-custom-dietary-style'),
                          initialValue: _customDietaryStyle,
                          maxLength: 100,
                          decoration: const InputDecoration(
                            border: OutlineInputBorder(),
                            labelText: 'Describe your custom dietary style',
                          ),
                          onChanged: (value) => _customDietaryStyle = value,
                        ),
                      ],
                      const SizedBox(height: 12),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text(
                          'Health conditions (optional wellness context):',
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 8,
                        runSpacing: 4,
                        children: [
                          'None',
                          'Diabetes',
                          'Hypertension',
                          'Heart health',
                          'PCOS',
                          'High cholesterol',
                          'Lactose intolerance',
                        ].map((cond) {
                          final isNone = cond == 'None';
                          final selected = isNone
                              ? _healthConditions.isEmpty || _healthConditions.contains('None')
                              : _healthConditions.contains(cond);
                          return FilterChip(
                            label: Text(cond),
                            selected: selected,
                            onSelected: (val) {
                              setState(() {
                                if (isNone) {
                                  if (val) {
                                    _healthConditions.clear();
                                    _healthConditions.add('None');
                                  }
                                } else {
                                  _healthConditions.remove('None');
                                  if (val) {
                                    _healthConditions.add(cond);
                                  } else {
                                    _healthConditions.remove(cond);
                                  }
                                }
                              });
                            },
                          );
                        }).toList(),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Conditions record your wellness context for guidance only; NutriLens does not diagnose or prescribe medical treatments.',
                        style: TextStyle(fontSize: 11),
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        key: const Key('profile-units'),
                        initialValue: _unitSystem,
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          labelText: 'Units',
                        ),
                        items: const [
                          DropdownMenuItem(
                            value: 'METRIC',
                            child: Text('Metric (kg, cm, ml)'),
                          ),
                          DropdownMenuItem(
                            value: 'IMPERIAL',
                            child: Text('Imperial (lb, ft, fl oz)'),
                          ),
                        ],
                        onChanged: (value) =>
                            setState(() => _unitSystem = value ?? 'METRIC'),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Personalize wellness guidance'),
                        subtitle: const Text(
                          'Use my saved profile to contextualize observed evidence.',
                        ),
                        value: _personalizationConsent,
                        onChanged: (value) =>
                            setState(() => _personalizationConsent = value),
                      ),
                      CheckboxListTile(
                        key: const Key('research-consent'),
                        contentPadding: EdgeInsets.zero,
                        title: const Text(
                          'Help improve nutrition research and product insights',
                        ),
                        subtitle: const Text(
                          'Optional and withdrawable. Identifiable account and Health Connect data are excluded.',
                        ),
                        value: _researchConsent,
                        onChanged: (value) =>
                            setState(() => _researchConsent = value ?? false),
                      ),
                      if (_notice != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(
                            _notice!,
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
}

String _formatDate(DateTime? value) {
  if (value == null) return '';
  return '${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';
}

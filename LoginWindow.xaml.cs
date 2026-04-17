using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows;

// Resolve ambiguous reference with System.Windows.Forms
using MessageBox = System.Windows.MessageBox;

namespace ApoptosisUI;

public partial class LoginWindow : Window
{
    private readonly UserManager _userManager;

    public string? LoggedInUsername { get; private set; }
    public bool IsGuest { get; private set; }

    public LoginWindow()
    {
        InitializeComponent();
        _userManager = new UserManager();
    }

    private void LoginButton_Click(object sender, RoutedEventArgs e)
    {
        var username = UsernameBox.Text?.Trim();
        var password = PasswordBox.Password;

        if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
        {
            ShowError(ErrorText, "Please enter username and password.");
            return;
        }

        if (_userManager.ValidateUser(username, password))
        {
            LoggedInUsername = username;
            IsGuest = false;
            DialogResult = true;
            Close();
        }
        else
        {
            ShowError(ErrorText, "Invalid username or password.");
        }
    }

    private void GuestButton_Click(object sender, RoutedEventArgs e)
    {
        LoggedInUsername = "Guest";
        IsGuest = true;
        DialogResult = true;
        Close();
    }

    private void ShowRegisterButton_Click(object sender, RoutedEventArgs e)
    {
        LoginForm.Visibility = Visibility.Collapsed;
        RegisterForm.Visibility = Visibility.Visible;
        ErrorText.Visibility = Visibility.Collapsed;
    }

    private void ShowLoginButton_Click(object sender, RoutedEventArgs e)
    {
        RegisterForm.Visibility = Visibility.Collapsed;
        LoginForm.Visibility = Visibility.Visible;
        RegErrorText.Visibility = Visibility.Collapsed;
    }

    private void RegisterButton_Click(object sender, RoutedEventArgs e)
    {
        var username = RegUsernameBox.Text?.Trim();
        var password = RegPasswordBox.Password;
        var confirmPassword = RegConfirmPasswordBox.Password;

        if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
        {
            ShowError(RegErrorText, "Please fill in all fields.");
            return;
        }

        if (username.Length < 3)
        {
            ShowError(RegErrorText, "Username must be at least 3 characters.");
            return;
        }

        if (password.Length < 4)
        {
            ShowError(RegErrorText, "Password must be at least 4 characters.");
            return;
        }

        if (password != confirmPassword)
        {
            ShowError(RegErrorText, "Passwords do not match.");
            return;
        }

        if (_userManager.UserExists(username))
        {
            ShowError(RegErrorText, "Username already exists.");
            return;
        }

        if (_userManager.RegisterUser(username, password))
        {
            MessageBox.Show("Account created successfully! You can now login.",
                "Registration Complete", MessageBoxButton.OK, MessageBoxImage.Information);
            ShowLoginButton_Click(sender, e);
            UsernameBox.Text = username;
        }
        else
        {
            ShowError(RegErrorText, "Failed to create account.");
        }
    }

    private static void ShowError(System.Windows.Controls.TextBlock errorText, string message)
    {
        errorText.Text = message;
        errorText.Visibility = Visibility.Visible;
    }
}

public class UserManager
{
    private readonly string _usersFilePath;
    private UsersData _data;

    public UserManager()
    {
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;
        _usersFilePath = Path.Combine(baseDir, "users.json");
        _data = LoadUsers();
    }

    private UsersData LoadUsers()
    {
        try
        {
            if (File.Exists(_usersFilePath))
            {
                var json = File.ReadAllText(_usersFilePath);
                return JsonSerializer.Deserialize<UsersData>(json) ?? new UsersData();
            }
        }
        catch { }
        return new UsersData();
    }

    private void SaveUsers()
    {
        try
        {
            var json = JsonSerializer.Serialize(_data, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(_usersFilePath, json);
        }
        catch { }
    }

    public bool UserExists(string username)
    {
        return _data.Users.Exists(u => u.Username.Equals(username, StringComparison.OrdinalIgnoreCase));
    }

    public bool ValidateUser(string username, string password)
    {
        var user = _data.Users.Find(u => u.Username.Equals(username, StringComparison.OrdinalIgnoreCase));
        if (user == null) return false;

        var hashedPassword = HashPassword(password, user.Salt);
        return user.PasswordHash == hashedPassword;
    }

    public bool RegisterUser(string username, string password)
    {
        if (UserExists(username)) return false;

        var salt = GenerateSalt();
        var hashedPassword = HashPassword(password, salt);

        _data.Users.Add(new UserInfo
        {
            Username = username,
            PasswordHash = hashedPassword,
            Salt = salt,
            CreatedAt = DateTime.Now
        });

        SaveUsers();
        return true;
    }

    private static string GenerateSalt()
    {
        var saltBytes = new byte[16];
        using var rng = RandomNumberGenerator.Create();
        rng.GetBytes(saltBytes);
        return Convert.ToBase64String(saltBytes);
    }

    private static string HashPassword(string password, string salt)
    {
        var combined = password + salt;
        var bytes = Encoding.UTF8.GetBytes(combined);
        var hash = SHA256.HashData(bytes);
        return Convert.ToBase64String(hash);
    }
}

public class UsersData
{
    public List<UserInfo> Users { get; set; } = new();
}

public class UserInfo
{
    public string Username { get; set; } = "";
    public string PasswordHash { get; set; } = "";
    public string Salt { get; set; } = "";
    public DateTime CreatedAt { get; set; }
}
